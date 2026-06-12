"""Engine 1 — microsimulation via PolicyEngine-US.

Pure: ReformSpec -> MicrosimResult. Knows nothing about callers.
Static microsim (no behavioral response) — labeled in the result assumptions.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

import numpy as np
from pydantic import BaseModel

from engines.spec import ReformSpec

STATIC_ASSUMPTION = (
    "Static microsimulation: no labor-supply or other behavioral response is modeled."
)


class StateImpact(BaseModel):
    total_change_usd: float        # aggregate household net-income change
    pct_change: float              # % change in aggregate household net income
    avg_change_per_household_usd: float


class DecileRow(BaseModel):
    decile: int
    avg_pct_change: float          # mean % change in household net income
    total_change_usd: float        # aggregate change for the decile
    avg_change_usd: float


class MicrosimResult(BaseModel):
    baseline_year: int
    state: str
    # The bridge number. Convention: change in (tax revenue - benefit outlays).
    # Negative = net cost to government; positive = net saving.
    budget_delta_usd: float
    # In-state aggregate change in household net income (the I-O injection
    # when spending.source == "budget_delta").
    in_state_household_gain_usd: float
    decile_table: list[DecileRow]
    households_better_off: float
    households_worse_off: float
    households_unchanged: float
    poverty_rate_baseline: float
    poverty_rate_reform: float
    gini_baseline: float
    gini_reform: float
    # state code -> impact (for the map)
    state_breakdown: dict[str, StateImpact]
    assumptions: list[str]


def _normalize_reforms(reforms: dict[str, Any], year: int) -> dict[str, Any]:
    """Scalar values apply from baseline_year onward; dicts pass through."""
    out: dict[str, Any] = {}
    for path, val in reforms.items():
        if isinstance(val, dict):
            out[path] = val
        else:
            out[path] = {f"{year}-01-01.2100-12-31": val}
    return out


@lru_cache(maxsize=1)
def _baseline_sim():
    from policyengine_us import Microsimulation

    return Microsimulation()


# Single-slot cache: one reformed Microsimulation is several GB, so keeping
# more than one (plus the baseline) can exhaust memory and get the process
# killed. Re-running the same reform in another geography stays instant;
# switching reforms pays a recompute (repeat specs hit the API's disk cache).
_reform_cache: dict[tuple[str, int], object] = {}


def _reform_sim(reforms_key: str, year: int):
    import gc
    import json

    key = (reforms_key, year)
    if key in _reform_cache:
        return _reform_cache[key]

    from policyengine_core.reforms import Reform
    from policyengine_us import Microsimulation

    _reform_cache.clear()
    gc.collect()  # actually release the previous simulation before building a new one
    reform = Reform.from_dict(
        _normalize_reforms(json.loads(reforms_key), year), country_id="us"
    )
    sim = Microsimulation(reform=reform)
    _reform_cache[key] = sim
    return sim


def validate_parameter_paths(paths: list[str]) -> dict[str, bool]:
    """Check candidate PolicyEngine parameter paths against the parameter tree.

    Handles bracket syntax for scale parameters (e.g. "...ctc.amount.base[0].amount"
    descends into children["base"].brackets[0])."""
    import re

    from policyengine_us.system import system

    known = {}
    for p in paths:
        try:
            node = system.parameters
            for part in p.split("."):
                m = re.fullmatch(r"([\w-]+)\[(\d+)\]", part)
                if m:
                    node = node.children[m.group(1)].brackets[int(m.group(2))]
                else:
                    node = node.children[part]
            known[p] = True
        except Exception:
            known[p] = False
    return known


def run_microsim(spec: ReformSpec) -> MicrosimResult:
    import json

    if spec.tax_transfer is None:
        raise ValueError("run_microsim called on a spec with no tax_transfer section")
    if spec.options.behavioral:
        raise NotImplementedError("Behavioral responses are not supported in v1 (static only)")

    tt = spec.tax_transfer
    year = tt.baseline_year
    state = spec.geography.state

    baseline = _baseline_sim()
    reformed = _reform_sim(json.dumps(tt.reforms, sort_keys=True), year)

    # Household-level arrays (MicroSeries carry survey weights)
    hh_net_base = baseline.calculate("household_net_income", period=year)
    hh_net_ref = reformed.calculate("household_net_income", period=year)
    hh_tax_base = baseline.calculate("household_tax", period=year)
    hh_tax_ref = reformed.calculate("household_tax", period=year)
    hh_ben_base = baseline.calculate("household_benefits", period=year)
    hh_ben_ref = reformed.calculate("household_benefits", period=year)
    hh_state = baseline.calculate("state_code", period=year).values
    hh_weights = hh_net_base.weights.values

    d_net = hh_net_ref.values - hh_net_base.values
    d_tax = hh_tax_ref.values - hh_tax_base.values
    d_ben = hh_ben_ref.values - hh_ben_base.values

    # Bridge: change in government balance = d(tax) - d(benefits)
    budget_delta = float(np.sum((d_tax - d_ben) * hh_weights))

    in_state = np.ones_like(hh_weights, dtype=bool) if state == "US" else (hh_state == state)
    in_state_gain = float(np.sum(d_net[in_state] * hh_weights[in_state]))

    state_breakdown: dict[str, StateImpact] = {}
    for sc in np.unique(hh_state):
        m = hh_state == sc
        w = hh_weights[m]
        chg = float(np.sum(d_net[m] * w))
        base_sum = float(np.sum(hh_net_base.values[m] * w))
        n_hh = float(np.sum(w))
        # A non-positive baseline aggregate (possible in small-state survey
        # samples with extreme negative incomes) makes % change meaningless.
        pct = 100.0 * chg / base_sum if base_sum > 0 else 0.0
        state_breakdown[str(sc)] = StateImpact(
            total_change_usd=chg,
            pct_change=pct,
            avg_change_per_household_usd=chg / n_hh if n_hh else 0.0,
        )

    # Distributional table by baseline income decile (in-state households)
    decile = baseline.calculate("household_income_decile", period=year).values
    rows: list[DecileRow] = []
    base_vals = hh_net_base.values
    for d in range(1, 11):
        m = in_state & (decile == d)
        w = hh_weights[m]
        if w.sum() == 0:
            rows.append(DecileRow(decile=d, avg_pct_change=0.0, total_change_usd=0.0, avg_change_usd=0.0))
            continue
        base_sum = float(np.sum(base_vals[m] * w))
        chg_sum = float(np.sum(d_net[m] * w))
        rows.append(
            DecileRow(
                decile=d,
                avg_pct_change=100.0 * chg_sum / base_sum if base_sum > 0 else 0.0,
                total_change_usd=chg_sum,
                avg_change_usd=chg_sum / float(w.sum()),
            )
        )

    w_in = hh_weights[in_state]
    better = float(np.sum(w_in[d_net[in_state] > 1.0]))
    worse = float(np.sum(w_in[d_net[in_state] < -1.0]))
    unchanged = float(np.sum(w_in)) - better - worse

    # Poverty (SPM, person-level) and Gini (equivalised income, person-level)
    pov_base = baseline.calculate("in_poverty", map_to="person", period=year)
    pov_ref = reformed.calculate("in_poverty", map_to="person", period=year)
    p_state = baseline.calculate("state_code", map_to="person", period=year).values
    p_in = np.ones(len(p_state), dtype=bool) if state == "US" else (p_state == state)
    pw = pov_base.weights.values
    pw_total = float(np.sum(pw[p_in]))
    if pw_total > 0:
        pov_rate_base = float(np.sum(pov_base.values[p_in] * pw[p_in]) / pw_total)
        pov_rate_ref = float(np.sum(pov_ref.values[p_in] * pw[p_in]) / pw_total)
    else:  # no sampled persons in this geography
        pov_rate_base = pov_rate_ref = 0.0

    gini_base, gini_ref = _gini_pair(baseline, reformed, year, p_in)

    return MicrosimResult(
        baseline_year=year,
        state=state,
        budget_delta_usd=budget_delta,
        in_state_household_gain_usd=in_state_gain,
        decile_table=rows,
        households_better_off=better,
        households_worse_off=worse,
        households_unchanged=unchanged,
        poverty_rate_baseline=pov_rate_base,
        poverty_rate_reform=pov_rate_ref,
        gini_baseline=gini_base,
        gini_reform=gini_ref,
        state_breakdown=state_breakdown,
        assumptions=[
            STATIC_ASSUMPTION,
            "Decile table uses baseline income deciles (national) restricted to in-state households.",
            "Poverty is the Supplemental Poverty Measure (SPM), person-level.",
            "The microdata is calibrated to national totals; small-state estimates "
            "carry extra sampling noise.",
        ],
    )


def _weighted_gini(values: np.ndarray, weights: np.ndarray) -> float:
    if len(values) == 0 or np.sum(weights) <= 0:
        return 0.0
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cw = np.cumsum(w)
    cv = np.cumsum(v * w)
    if cv[-1] == 0:
        return 0.0
    # Trapezoidal Lorenz-curve integration (curve must start at the origin)
    lorenz = np.concatenate([[0.0], cv / cv[-1]])
    pop = np.concatenate([[0.0], cw / cw[-1]])
    b = np.trapezoid(lorenz, pop)
    return float(1 - 2 * b)


def _gini_pair(baseline, reformed, year: int, person_mask: np.ndarray) -> tuple[float, float]:
    try:
        eq_base = baseline.calculate("equiv_household_net_income", map_to="person", period=year)
        eq_ref = reformed.calculate("equiv_household_net_income", map_to="person", period=year)
    except Exception:
        eq_base = baseline.calculate("household_net_income", map_to="person", period=year)
        eq_ref = reformed.calculate("household_net_income", map_to="person", period=year)
    w = eq_base.weights.values
    vb = np.clip(eq_base.values, 0, None)
    vr = np.clip(eq_ref.values, 0, None)
    return (
        _weighted_gini(vb[person_mask], w[person_mask]),
        _weighted_gini(vr[person_mask], w[person_mask]),
    )
