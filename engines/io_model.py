"""Engine 2 — regional input-output multipliers (LQ-regionalized Leontief).

Method (RIMS II-style, built from free public data):
1. National direct-requirements matrix A (BEA, sector level, 15 industries).
2. Import-adjust: multiply each commodity row by its domestic share (from the
   BEA Use table's imports column) so coefficients reflect domestic supply.
3. Regionalize: scale each row by min(1, SLQ_i), the simple employment
   location quotient from QCEW — industries under-represented in the state
   supply less of local demand (the rest leaks out of the region).
4. Type I: L = (I - A_region)^-1  (direct + indirect).
   Type II: close the model with a household row (compensation per dollar of
   output, wage-level-adjusted to the state) and a household consumption
   column (PCE shares x domestic share x LQ x marginal propensity to consume).
5. Jobs from national employment-per-output by sector, adjusted by the
   state/national wage ratio (higher-wage states -> fewer jobs per dollar).

Known bias, labeled in every result: LQ methods overstate multipliers (no
cross-hauling correction). Low/high scenarios vary the leakage and MPC
assumptions; they are heuristic sensitivity bands, not confidence intervals.

Pure: (state, spending shock) -> IOResult. Knows nothing about callers.
"""
from __future__ import annotations

import difflib
from typing import Literal, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel

from data.fetch import (
    BEA_SECTOR_NAMES,
    BEA_SECTORS,
    bea_direct_requirements,
    bea_use_aggregates,
    qcew_sector_employment,
    state_area_fips,
)

LQ_OVERSTATEMENT_ASSUMPTION = (
    "Fixed-coefficient I-O model regionalized with simple location quotients "
    "(SLQ); this method tends to OVERSTATE multipliers because it ignores "
    "cross-hauling. Low/high are heuristic sensitivity bands, not confidence intervals."
)

# Scenario parameter sets: mpc = marginal propensity to consume locally-relevant
# consumption out of additional earnings; lq_damp scales the location quotients
# (more damping = more leakage out of the state).
SCENARIOS = {
    "low": {"mpc": 0.55, "lq_damp": 0.85},
    "central": {"mpc": 0.70, "lq_damp": 1.0},
    "high": {"mpc": 0.80, "lq_damp": 1.0},
}


class IndustryEffect(BaseModel):
    sector: str
    sector_name: str
    output_usd: float
    earnings_usd: float
    jobs: float


class TypeScenarioEffect(BaseModel):
    output_usd: float
    earnings_usd: float
    jobs: float
    output_multiplier: float  # total output per dollar of shock


class IOResult(BaseModel):
    state: str
    io_year: str
    shock_kind: Literal["industry_spending", "household_income"]
    shock_total_usd: float
    # spending vector actually fed to the model (after industry matching)
    spending_vector: dict[str, float]
    # effects["I"]["central"] etc.
    effects: dict[str, dict[str, TypeScenarioEffect]]
    # central-scenario per-industry breakdown, by multiplier type
    by_industry: dict[str, list[IndustryEffect]]
    assumptions: list[str]


class RegionalIOModel:
    """All matrices for one state, built once and reused across shocks."""

    def __init__(self, state: str, area_fips: Optional[str] = None, label: Optional[str] = None):
        """state: USPS code (labels the result). area_fips: QCEW area override
        for sub-state geographies (e.g. 'C1670' for an MSA)."""
        self.state = state.upper()
        self.label = label or self.state
        self.sectors = list(BEA_SECTORS)
        self.sector_names = dict(BEA_SECTOR_NAMES)
        dr = bea_direct_requirements()
        use = bea_use_aggregates()
        self.A_nat = dr.loc[BEA_SECTORS, BEA_SECTORS].values
        self.comp_row = dr.loc["V001", BEA_SECTORS].values  # earnings per $ output
        self.domestic_share = use["domestic_share"].values
        self.pce_share = (use["pce"] / use["pce"].sum()).values
        self.gross_output_usd = use["gross_output"].values * 1e6  # table is $mn

        nat = qcew_sector_employment("US000")
        st = qcew_sector_employment(area_fips or state_area_fips(self.state))
        self.emp_nat = nat["employment"].values
        self.emp_state = st["employment"].values

        # Simple location quotients (employment-based)
        nat_share = self.emp_nat / self.emp_nat.sum()
        st_share = self.emp_state / self.emp_state.sum()
        with np.errstate(divide="ignore", invalid="ignore"):
            self.slq = np.where(nat_share > 0, st_share / nat_share, 0.0)

        # Wage-level ratio (state vs national average pay per worker, by sector)
        with np.errstate(divide="ignore", invalid="ignore"):
            nat_pay = np.where(self.emp_nat > 0, nat["wages"].values / np.maximum(self.emp_nat, 1), 1.0)
            st_pay = np.where(self.emp_state > 0, st["wages"].values / np.maximum(self.emp_state, 1), nat_pay)
            self.wage_ratio = np.clip(np.where(nat_pay > 0, st_pay / nat_pay, 1.0), 0.5, 2.0)

        # National jobs per dollar of gross output, by sector
        self.jobs_per_usd_nat = self.emp_nat / self.gross_output_usd

    def _matrices(self, scenario: str):
        p = SCENARIOS[scenario]
        rlq = np.clip(self.slq * p["lq_damp"], 0.0, 1.0)
        A_dom = self.A_nat * self.domestic_share[:, None]
        A_reg = A_dom * rlq[:, None]
        n = len(self.sectors)
        L1 = np.linalg.inv(np.eye(n) - A_reg)

        # Type II closure: household earnings row + consumption column.
        # comp_row (compensation per $ of output) is a production-recipe ratio
        # and is NOT wage-adjusted; the state wage level instead adjusts jobs
        # per dollar (higher-wage state -> fewer jobs for the same payroll).
        h_row = self.comp_row
        c_col = p["mpc"] * self.pce_share * self.domestic_share * rlq
        A2 = np.zeros((n + 1, n + 1))
        A2[:n, :n] = A_reg
        A2[:n, n] = c_col
        A2[n, :n] = h_row
        L2 = np.linalg.inv(np.eye(n + 1) - A2)
        return L1, L2, rlq, p

    def consumption_demand(self, household_income_usd: float, scenario: str) -> np.ndarray:
        """First-round local final demand from an exogenous household income change."""
        p = SCENARIOS[scenario]
        rlq = np.clip(self.slq * p["lq_damp"], 0.0, 1.0)
        return household_income_usd * p["mpc"] * self.pce_share * self.domestic_share * rlq

    def run_shock(
        self,
        spending_by_sector: dict[str, float],
        shock_kind: Literal["industry_spending", "household_income"],
        shock_total_usd: float,
        scenarios: list[str],
        multiplier_types: list[str],
    ) -> IOResult:
        n = len(self.sectors)
        idx = {s: i for i, s in enumerate(self.sectors)}

        effects: dict[str, dict[str, TypeScenarioEffect]] = {t: {} for t in multiplier_types}
        by_industry: dict[str, list[IndustryEffect]] = {}

        for scen in scenarios:
            L1, L2, rlq, p = self._matrices(scen)

            if shock_kind == "household_income":
                f = self.consumption_demand(shock_total_usd, scen)
            else:
                f = np.zeros(n)
                for sector, amount in spending_by_sector.items():
                    f[idx[sector]] += amount

            h_row = self.comp_row
            jobs_per_usd = self.jobs_per_usd_nat / self.wage_ratio

            for mtype in multiplier_types:
                if mtype == "I":
                    dX = L1 @ f
                else:
                    f2 = np.append(f, 0.0)
                    dX = (L2 @ f2)[:n]
                # Signed/signed division keeps the multiplier positive for
                # withdrawals; a zero shock has no meaningful multiplier.
                mult = float(dX.sum() / shock_total_usd) if shock_total_usd else 0.0
                eff = TypeScenarioEffect(
                    output_usd=float(dX.sum()),
                    earnings_usd=float(h_row @ dX),
                    jobs=float(jobs_per_usd @ dX),
                    output_multiplier=mult,
                )
                effects[mtype][scen] = eff
                if scen == "central":
                    by_industry[mtype] = [
                        IndustryEffect(
                            sector=s,
                            sector_name=self.sector_names.get(s, s),
                            output_usd=float(dX[i]),
                            earnings_usd=float(h_row[i] * dX[i]),
                            jobs=float(jobs_per_usd[i] * dX[i]),
                        )
                        for i, s in enumerate(self.sectors)
                    ]

        return IOResult(
            state=self.state,
            io_year="2023",
            shock_kind=shock_kind,
            shock_total_usd=shock_total_usd,
            spending_vector={s: float(v) for s, v in spending_by_sector.items()},
            effects=effects,
            by_industry=by_industry,
            assumptions=[
                LQ_OVERSTATEMENT_ASSUMPTION,
                "BEA sector-level resolution (15 industries); named programs are "
                "matched to the closest sector.",
                "Jobs use national employment-per-output by sector, adjusted by the "
                "state/national wage ratio.",
                (
                    "Household-income shocks enter as first-round consumption "
                    "(MPC x PCE shares x local supply), so even Type I includes that "
                    "first spending round."
                    if shock_kind == "household_income"
                    else "Industry spending is assumed to be spent at in-state producers."
                ),
            ],
        )


def match_industry(name: str) -> str:
    """Fuzzy-match a free-text industry name to a BEA sector code."""
    name_l = name.strip().lower()
    for code, full in BEA_SECTOR_NAMES.items():
        if name_l == full.lower() or name_l == code.lower():
            return code
    # keyword shortcuts for common program language (whole-word match so
    # e.g. "road" never matches inside "broadband")
    import re

    keywords = {
        "broadband": "51", "transit": "48TW", "transportation": "48TW",
        "rail": "48TW", "bus": "48TW",
        "highway": "23", "highways": "23", "road": "23", "roads": "23",
        "bridge": "23", "bridges": "23", "infrastructure": "23", "housing": "23",
        "school": "6", "schools": "6", "education": "6",
        "health": "6", "healthcare": "6", "hospital": "6", "hospitals": "6",
        "childcare": "6", "child care": "6",
        "police": "G", "defense": "G", "military": "G",
        "farm": "11", "farms": "11", "agriculture": "11",
        "energy": "22", "water": "22", "utility": "22", "utilities": "22",
        "factory": "31G", "factories": "31G", "manufacturing": "31G",
        "semiconductor": "31G", "semiconductors": "31G",
        "tourism": "7", "restaurant": "7", "restaurants": "7", "hotel": "7", "hotels": "7",
        "research": "PROF", "r&d": "PROF",
    }
    for kw, code in keywords.items():
        if re.search(rf"(?<![\w]){re.escape(kw)}(?![\w])", name_l):
            return code
    scores = {
        code: difflib.SequenceMatcher(None, name_l, full.lower()).ratio()
        for code, full in BEA_SECTOR_NAMES.items()
    }
    best = max(scores, key=scores.get)
    if scores[best] < 0.3:
        raise ValueError(
            f"Cannot match industry {name!r} to a BEA sector. "
            f"Valid sectors: {list(BEA_SECTOR_NAMES.values())}"
        )
    return best
