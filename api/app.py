"""FastAPI surface. Thin: validates, calls the same pipeline the CLI uses,
caches results on disk by spec hash (microsim runs take minutes).

Run: uv run uvicorn api.app:app --port 8000
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engines.pipeline import SimulationResult, run_pipeline
from engines.spec import ReformSpec

RESULTS_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Fiscal Policy Simulator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_run_lock = threading.Lock()  # PolicyEngine sims are not safely concurrent


# Bump when engine methodology changes, so stale cached results are not served
ENGINE_VERSION = "3"


def _spec_hash(spec: ReformSpec) -> str:
    canon = ENGINE_VERSION + json.dumps(spec.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def _read_cache(cache_file) -> Optional[SimulationResult]:
    """A torn or stale cache file is a cache miss, never an error."""
    if not cache_file.exists():
        return None
    try:
        return SimulationResult.model_validate_json(cache_file.read_text())
    except Exception:
        cache_file.unlink(missing_ok=True)
        return None


def _run_cached(spec: ReformSpec) -> SimulationResult:
    cache_file = RESULTS_DIR / f"{_spec_hash(spec)}.json"
    if (hit := _read_cache(cache_file)) is not None:
        return hit
    with _run_lock:
        if (hit := _read_cache(cache_file)) is not None:  # raced
            return hit
        result = run_pipeline(spec)
        if result.cacheable:
            tmp = cache_file.parent / (cache_file.name + ".tmp")
            tmp.write_text(result.model_dump_json())
            tmp.replace(cache_file)  # atomic — readers never see a torn file
        return result


def _run_for_api(spec: ReformSpec) -> SimulationResult:
    """Run with errors mapped to meaningful HTTP statuses."""
    import requests as _requests

    # Reject unknown PolicyEngine parameter paths up front with a clear 422
    if spec.tax_transfer is not None:
        from engines.microsim import validate_parameter_paths

        validity = validate_parameter_paths(list(spec.tax_transfer.reforms))
        unknown = sorted(p for p, ok in validity.items() if not ok)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown PolicyEngine parameter path(s): {', '.join(unknown)}",
            )
    try:
        return _run_cached(spec)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (_requests.RequestException, OSError) as e:
        raise HTTPException(
            status_code=503,
            detail=f"A public data source (BEA/BLS) could not be reached: {e}",
        )


@app.get("/health")
def health() -> dict:
    import os

    return {
        "ok": True,
        "ai_ingestion": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.post("/simulate", response_model=SimulationResult)
def simulate(spec: ReformSpec) -> SimulationResult:
    return _run_for_api(spec)


class MSARequest(BaseModel):
    state: str
    shock_kind: str  # "industry_spending" | "household_income"
    shock_total_usd: float
    spending_vector: dict[str, float] = {}


class MSAEffect(BaseModel):
    area: str
    title: str
    employment_share: float
    shock_usd: float
    jobs_type1: float
    jobs_type2: float
    output_type2_usd: float
    earnings_type2_usd: float


@app.post("/msa_breakdown", response_model=list[MSAEffect])
def msa_breakdown(req: MSARequest) -> list[MSAEffect]:
    """Drill the selected state's shock into its MSAs. The state total is
    apportioned by each MSA's share of state private employment; each MSA gets
    its own LQ-regionalized multipliers. MSA shares don't sum to 1 (rural
    areas are outside MSAs; multi-state MSAs are matched whole)."""
    from data.fetch import msa_areas, qcew_sector_employment, state_area_fips
    from engines.io_model import RegionalIOModel

    from data.fetch import BEA_SECTORS

    state = req.state.upper()
    bad_keys = sorted(set(req.spending_vector) - set(BEA_SECTORS))
    if bad_keys:
        raise HTTPException(
            status_code=422,
            detail=f"spending_vector keys must be BEA sector codes; unknown: {bad_keys}",
        )
    if req.shock_kind not in ("industry_spending", "household_income"):
        raise HTTPException(status_code=422, detail=f"Unknown shock_kind {req.shock_kind!r}")
    try:
        areas = msa_areas(state)
        state_emp = float(qcew_sector_employment(state_area_fips(state))["employment"].sum())
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Unknown state {req.state!r}")

    out: list[MSAEffect] = []
    failures = 0
    for fips, title in areas:
        try:
            model = RegionalIOModel(state, area_fips=fips, label=title)
            share = float(model.emp_state.sum()) / state_emp if state_emp else 0.0
            shock = req.shock_total_usd * share
            vector = {k: v * share for k, v in req.spending_vector.items()}
            res = model.run_shock(
                spending_by_sector=vector,
                shock_kind=req.shock_kind,  # type: ignore[arg-type]
                shock_total_usd=shock,
                scenarios=["central"],
                multiplier_types=["I", "II"],
            )
        except Exception:
            failures += 1
            continue  # suppressed/missing QCEW data for small areas
        out.append(
            MSAEffect(
                area=fips,
                title=title,
                employment_share=share,
                shock_usd=shock,
                jobs_type1=res.effects["I"]["central"].jobs,
                jobs_type2=res.effects["II"]["central"].jobs,
                output_type2_usd=res.effects["II"]["central"].output_usd,
                earnings_type2_usd=res.effects["II"]["central"].earnings_usd,
            )
        )
    if areas and failures == len(areas):
        raise HTTPException(
            status_code=502,
            detail=f"All {failures} MSA computations failed for {state} — "
            "likely a transient QCEW data-source problem; retry.",
        )
    out.sort(key=lambda e: abs(e.jobs_type2), reverse=True)
    return out


class InterpretRequest(BaseModel):
    text: str
    state: Optional[str] = None


class InterpretResponse(BaseModel):
    extraction: dict
    spec: Optional[dict] = None
    result: Optional[SimulationResult] = None
    warnings: list[str]
    ran: bool
    message: Optional[str] = None


@app.post("/interpret", response_model=InterpretResponse)
def interpret(req: InterpretRequest) -> InterpretResponse:
    """AI extraction -> validate -> auto-run. Never fabricates: if nothing is
    runnable, returns ran=False with the raw extraction and a readable message."""
    from ingestion.extract import (
        ExtractionFailed,
        IngestionUnavailable,
        build_spec,
        extract_provisions,
    )

    try:
        extraction = extract_provisions(req.text)
    except IngestionUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ExtractionFailed as e:
        raise HTTPException(status_code=422, detail=str(e))

    spec, warnings = build_spec(extraction, state_override=req.state)
    if spec is None:
        return InterpretResponse(
            extraction=extraction.model_dump(),
            warnings=warnings,
            ran=False,
            message=(
                "No runnable provisions could be mapped — nothing was simulated. "
                "Supply the missing lever and retry."
            ),
        )
    result = _run_for_api(spec)
    result.warnings.extend(warnings)
    return InterpretResponse(
        extraction=extraction.model_dump(),
        spec=spec.model_dump(mode="json"),
        result=result,
        warnings=warnings,
        ran=True,
    )
