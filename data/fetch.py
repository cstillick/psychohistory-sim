"""Data layer: fetch + parse + cache the free public tables the I-O engine needs.

Sources (no API keys required):
- BEA AllTablesIO.zip — national commodity-by-industry Direct Requirements
  (sector level, after redefinitions, producers' prices) and the Use table
  (for PCE shares, import shares, and industry gross output).
- BLS QCEW open CSV API — employment by NAICS sector, national and per state
  (for location quotients and jobs-per-output ratios).

Parsed tables are cached as Parquet under data/cache/.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"

BEA_IO_ZIP_URL = "https://apps.bea.gov/industry/iTables%20Static%20Files/AllTablesIO.zip"
DR_FILE = "CxI_DR_1997-2023_Sector.xlsx"
USE_FILE = "IOUse_After_Redefinitions_PRO_1997-2023_Sector.xlsx"
QCEW_URL = "https://data.bls.gov/cew/data/api/{year}/a/area/{area}.csv"

IO_YEAR = "2023"   # latest year in the BEA sector files
QCEW_YEAR = 2023   # keep employment year aligned with the I-O year
# Bump when the parsing logic changes so stale parquet caches are not reused
PARSER_VERSION = "2"

# The 15 BEA sector-level industries
BEA_SECTORS = [
    "11", "21", "22", "23", "31G", "42", "44RT", "48TW",
    "51", "FIRE", "PROF", "6", "7", "81", "G",
]
BEA_SECTOR_NAMES = {
    "11": "Agriculture, forestry, fishing, and hunting",
    "21": "Mining",
    "22": "Utilities",
    "23": "Construction",
    "31G": "Manufacturing",
    "42": "Wholesale trade",
    "44RT": "Retail trade",
    "48TW": "Transportation and warehousing",
    "51": "Information",
    "FIRE": "Finance, insurance, real estate, rental, and leasing",
    "PROF": "Professional and business services",
    "6": "Educational services, health care, and social assistance",
    "7": "Arts, entertainment, recreation, accommodation, and food services",
    "81": "Other services, except government",
    "G": "Government",
}

# NAICS 2-digit sector -> BEA sector code (private ownership)
NAICS_TO_BEA = {
    "11": "11", "21": "21", "22": "22", "23": "23", "31-33": "31G",
    "42": "42", "44-45": "44RT", "48-49": "48TW", "51": "51",
    "52": "FIRE", "53": "FIRE", "54": "PROF", "55": "PROF", "56": "PROF",
    "61": "6", "62": "6", "71": "7", "72": "7", "81": "81",
}

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
}


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_bea_files() -> None:
    """Download and extract the BEA I-O workbooks if missing."""
    _ensure_dirs()
    if (RAW_DIR / DR_FILE).exists() and (RAW_DIR / USE_FILE).exists():
        return
    resp = requests.get(BEA_IO_ZIP_URL, timeout=300)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in (DR_FILE, USE_FILE):
            zf.extract(name, RAW_DIR)


def _write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    """Write-then-rename so concurrent readers never see a torn file."""
    tmp = path.parent / (path.name + ".tmp")
    df.to_parquet(tmp)
    tmp.replace(path)


def _parse_bea_sheet(path: Path, year: str) -> pd.DataFrame:
    """Parse a BEA sector workbook sheet into a DataFrame indexed by row code
    with header-code columns.

    Position-aware: BEA sheets contain UNLABELED total rows/columns (e.g.
    'Total Intermediate' has no code). Columns are mapped by their absolute
    position in the header so an unlabeled column never shifts the labeled
    ones, and unlabeled rows are skipped rather than terminating the parse
    (the value-added rows V001-V003 come after them)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[year]
    rows = list(ws.iter_rows(values_only=True))
    col_pos = {str(c): i for i, c in enumerate(rows[5]) if i >= 2 and c is not None}
    data: dict[str, list[float]] = {}
    for r in rows[7:]:
        code = r[0]
        if code is None:
            continue  # unlabeled total row — skip, don't stop
        s = str(code)
        if s.startswith(("1.", "Note")):
            break  # footnotes
        vals = []
        for i in col_pos.values():
            x = r[i] if i < len(r) else None
            vals.append(float(x) if x not in (None, "...") else 0.0)
        data[s] = vals
    return pd.DataFrame.from_dict(data, orient="index", columns=list(col_pos))


def bea_direct_requirements() -> pd.DataFrame:
    """National direct-requirements coefficients (15x15, commodity x industry),
    plus the V001 compensation row, as a DataFrame indexed by row code."""
    cache = CACHE_DIR / f"bea_dr_{IO_YEAR}_v{PARSER_VERSION}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    _ensure_bea_files()
    df = _parse_bea_sheet(RAW_DIR / DR_FILE, IO_YEAR)
    df = df.loc[BEA_SECTORS + ["V001"], BEA_SECTORS]
    # Direct-requirements columns (inputs + value added) must sum to ~1
    full = _parse_bea_sheet(RAW_DIR / DR_FILE, IO_YEAR)
    colsums = full.loc[[c for c in full.index if not c.startswith(("T",))], BEA_SECTORS].sum(axis=0)
    if not np.allclose(colsums.values, 1.0, atol=0.02):
        raise RuntimeError(f"BEA DR parse sanity failed: column sums {colsums.values}")
    _write_parquet_atomic(df, cache)
    return df


# Final-use columns of the Use table
FINAL_USE_COLS = ["F010", "F020", "F030", "F040", "F050", "F100"]
VALUE_ADDED_ROWS = ["V001", "V002", "V003"]


def bea_use_aggregates() -> pd.DataFrame:
    """Per-sector aggregates from the Use table (millions of dollars):
    pce (F010), imports (positive), domestic commodity output, industry
    gross_output (intermediate inputs + value added), domestic_share."""
    cache = CACHE_DIR / f"bea_use_{IO_YEAR}_v{PARSER_VERSION}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    _ensure_bea_files()
    df = _parse_bea_sheet(RAW_DIR / USE_FILE, IO_YEAR)

    sec = df.loc[BEA_SECTORS]
    pce = sec["F010"]
    # F050 (imports) is negative for goods/services sectors; the trade sectors
    # can be positive (domestic margins on imported goods are recorded there).
    if not ((sec["F050"] > 0).sum() <= 3 and sec["F050"].sum() < 0):
        raise RuntimeError(
            "BEA Use parse sanity failed: imports column looks wrong — "
            f"F050 = {sec['F050'].values}"
        )
    imports = (-sec["F050"]).clip(lower=0.0)
    # Commodity output = intermediate use by industries + all final uses
    # (imports enter negatively). Explicit column selection — never row sums
    # that could pick up unlabeled totals.
    commodity_output = sec[BEA_SECTORS].sum(axis=1) + sec[FINAL_USE_COLS].sum(axis=1)
    total_supply = commodity_output + imports
    domestic_share = (commodity_output / total_supply).clip(0, 1)
    if (domestic_share >= 0.999).sum() > 8:
        raise RuntimeError(
            "BEA Use parse sanity failed: domestic share ~1 for most sectors — "
            "import column is being missed"
        )
    # Industry gross output = intermediate inputs + value added
    input_rows = [r for r in df.index if r in BEA_SECTORS + ["Used", "Other"] + VALUE_ADDED_ROWS]
    gross_output = df.loc[input_rows, BEA_SECTORS].sum(axis=0)
    va = df.loc[VALUE_ADDED_ROWS, BEA_SECTORS].sum(axis=0)
    if not (va > 0).all():
        raise RuntimeError("BEA Use parse sanity failed: value added must be positive")

    out = pd.DataFrame(
        {
            "pce": pce,
            "imports": imports,
            "domestic_output": commodity_output,
            "domestic_share": domestic_share,
            "gross_output": gross_output.reindex(BEA_SECTORS).values,
        },
        index=BEA_SECTORS,
    )
    _write_parquet_atomic(out, cache)
    return out


def qcew_sector_employment(area_fips: str) -> pd.DataFrame:
    """Annual average employment and wages by BEA sector for a QCEW area
    (e.g. 'US000' national, '45000' South Carolina). Private ownership for
    NAICS sectors; federal+state+local government totals mapped to 'G'."""
    cache = CACHE_DIR / f"qcew_{QCEW_YEAR}_{area_fips}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    _ensure_dirs()
    url = QCEW_URL.format(year=QCEW_YEAR, area=area_fips)
    raw = pd.read_csv(url, dtype={"industry_code": str, "own_code": str, "area_fips": str})

    private = raw[(raw["own_code"] == "5") & (raw["industry_code"].isin(NAICS_TO_BEA))]
    gov = raw[(raw["own_code"].isin(["1", "2", "3"])) & (raw["industry_code"] == "10")]

    rows = []
    for naics, bea in NAICS_TO_BEA.items():
        sub = private[private["industry_code"] == naics]
        rows.append(
            {
                "bea_sector": bea,
                "employment": float(sub["annual_avg_emplvl"].sum()),
                "wages": float(sub["total_annual_wages"].sum()),
            }
        )
    rows.append(
        {
            "bea_sector": "G",
            "employment": float(gov["annual_avg_emplvl"].sum()),
            "wages": float(gov["total_annual_wages"].sum()),
        }
    )
    df = pd.DataFrame(rows).groupby("bea_sector", as_index=True).sum()
    df = df.reindex(BEA_SECTORS).fillna(0.0)
    _write_parquet_atomic(df, cache)
    return df


def state_area_fips(state: str) -> str:
    return STATE_FIPS[state.upper()] + "000"


AREA_TITLES_URL = "https://data.bls.gov/cew/doc/titles/area/area_titles.csv"


def msa_areas(state: str) -> list[tuple[str, str]]:
    """QCEW MSA areas attributed to a state: [(area_fips, title), ...].
    A multi-state MSA (e.g. 'Charlotte-Concord-Gastonia, NC-SC MSA') is
    attributed only to its PRIMARY state (first in the suffix) — QCEW reports
    whole-MSA employment, so splitting it across states would double-count.
    MicroSAs are excluded."""
    import re

    _ensure_dirs()
    cache = CACHE_DIR / "qcew_area_titles.parquet"
    if cache.exists():
        titles = pd.read_parquet(cache)
    else:
        titles = pd.read_csv(AREA_TITLES_URL, dtype=str)
        titles.columns = ["area_fips", "area_title"]
        titles = titles.drop_duplicates(subset="area_fips")
        _write_parquet_atomic(titles, cache)
    state = state.upper()
    out: dict[str, str] = {}
    for _, row in titles.iterrows():
        fips, title = row["area_fips"], row["area_title"]
        if not fips.startswith("C") or not title.endswith(" MSA"):
            continue
        m = re.search(r", ([A-Z-]+) MSA$", title)
        if m and m.group(1).split("-")[0] == state:
            out[fips] = title.removesuffix(" MSA")
    return sorted(out.items())
