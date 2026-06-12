"""The unification: one reform spec -> microsim -> budget delta -> I-O.

Two panels, one bridge. The bridge is the net budget delta (microsim side)
which becomes the spending shock (I-O side). The two halves are NEVER summed
into a single blended dollar figure — see build spec §5.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from engines.io_model import IOResult, RegionalIOModel, match_industry
from engines.microsim import MicrosimResult, run_microsim
from engines.spec import ReformSpec


class Bridge(BaseModel):
    """The number that links the two panels."""

    budget_delta_usd: Optional[float] = None        # change in gov balance (negative = cost)
    io_shock_usd: Optional[float] = None            # what was actually fed to the I-O engine
    io_shock_source: Optional[str] = None           # "budget_delta" | "explicit_program"
    note: str = (
        "The two panels rest on different models and assumptions; their dollar "
        "figures must not be added together."
    )


class StateJobs(BaseModel):
    """Per-state I-O effects for the national map (budget-delta shocks only)."""

    shock_usd: float
    jobs_type1: float
    jobs_type2: float
    jobs_type2_low: float
    jobs_type2_high: float
    output_type2_usd: float
    earnings_type2_usd: float


class SimulationResult(BaseModel):
    spec: ReformSpec
    microsim: Optional[MicrosimResult] = None
    io: Optional[IOResult] = None
    # state -> jobs/output/earnings from that state's share of the household
    # gain (only for budget_delta shocks, where the gain spreads nationally)
    io_by_state: Optional[dict[str, StateJobs]] = None
    bridge: Bridge
    assumptions: list[str]
    warnings: list[str]
    # False when part of the result is missing for transient reasons (e.g. a
    # data fetch failed for one state) — such results must not be cached.
    cacheable: bool = True


def _io_by_state(micro: MicrosimResult, warnings: list[str]) -> dict[str, StateJobs]:
    """Run the I-O model in every state on that state's share of the household
    gain. Cheap after the first run (QCEW per-state files are cached)."""
    out: dict[str, StateJobs] = {}
    for state, impact in micro.state_breakdown.items():
        if abs(impact.total_change_usd) < 1.0:
            continue
        try:
            model = RegionalIOModel(state)
            res = model.run_shock(
                spending_by_sector={},
                shock_kind="household_income",
                shock_total_usd=impact.total_change_usd,
                scenarios=["low", "central", "high"],
                multiplier_types=["I", "II"],
            )
        except KeyError:
            # Not a mappable jurisdiction (no QCEW area) — permanent, cacheable
            warnings.append(f"No I-O geography for {state}; omitted from the map.")
            continue
        except Exception as e:  # network failure etc. — transient, not cacheable
            warnings.append(f"I-O breakdown unavailable for {state}: {e}")
            continue
        out[state] = StateJobs(
            shock_usd=impact.total_change_usd,
            jobs_type1=res.effects["I"]["central"].jobs,
            jobs_type2=res.effects["II"]["central"].jobs,
            jobs_type2_low=res.effects["II"]["low"].jobs,
            jobs_type2_high=res.effects["II"]["high"].jobs,
            output_type2_usd=res.effects["II"]["central"].output_usd,
            earnings_type2_usd=res.effects["II"]["central"].earnings_usd,
        )
    return out


def run_pipeline(spec: ReformSpec) -> SimulationResult:
    warnings: list[str] = []
    micro: Optional[MicrosimResult] = None
    io_res: Optional[IOResult] = None
    by_state: Optional[dict[str, StateJobs]] = None
    bridge = Bridge()

    if spec.tax_transfer is not None:
        micro = run_microsim(spec)
        bridge.budget_delta_usd = micro.budget_delta_usd

    if spec.spending is not None:
        state = spec.geography.state
        if state == "US":
            raise ValueError(
                "The I-O engine is regional: set geography.state to a state code "
                "to run the spending side (the microsim side can stay national)."
            )
        model = RegionalIOModel(state)

        if spec.spending.source == "budget_delta":
            assert micro is not None  # enforced by the spec schema
            shock = micro.in_state_household_gain_usd
            if abs(shock) < 1.0:
                warnings.append(
                    "Budget delta is ~zero in-state; the I-O side has nothing to model."
                )
            io_res = model.run_shock(
                spending_by_sector={},
                shock_kind="household_income",
                shock_total_usd=shock,
                scenarios=spec.options.scenarios,
                multiplier_types=spec.options.multiplier_types,
            )
            bridge.io_shock_usd = shock
            bridge.io_shock_source = "budget_delta"
            by_state = _io_by_state(micro, warnings)
        else:
            vector: dict[str, float] = {}
            for item in spec.spending.explicit_program:
                code = match_industry(item.industry)
                vector[code] = vector.get(code, 0.0) + item.amount_usd
            total = sum(vector.values())
            io_res = model.run_shock(
                spending_by_sector=vector,
                shock_kind="industry_spending",
                shock_total_usd=total,
                scenarios=spec.options.scenarios,
                multiplier_types=spec.options.multiplier_types,
            )
            bridge.io_shock_usd = total
            bridge.io_shock_source = "explicit_program"

    assumptions: list[str] = []
    if micro is not None:
        assumptions += micro.assumptions
    if io_res is not None:
        assumptions += io_res.assumptions
    assumptions.append(bridge.note)

    return SimulationResult(
        spec=spec,
        microsim=micro,
        io=io_res,
        io_by_state=by_state,
        bridge=bridge,
        assumptions=assumptions,
        warnings=warnings,
        cacheable=not any(w.startswith("I-O breakdown unavailable") for w in warnings),
    )
