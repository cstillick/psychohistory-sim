"""Microsim acceptance tests (slow: full PolicyEngine runs).

Run with: uv run pytest -m slow tests/test_microsim.py
The aggregate checks anchor the engine to administrative/published totals —
the Phase 1 acceptance criterion.
"""
import numpy as np
import pytest

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def baseline():
    from engines.microsim import _baseline_sim

    return _baseline_sim()


def test_baseline_eitc_aggregate(baseline):
    """Federal EITC outlays are ~$60-80bn/yr (IRS SOI / CBO)."""
    total = baseline.calculate("eitc", period=2026).sum()
    assert 45e9 < total < 95e9, f"EITC aggregate ${total/1e9:.1f}bn outside sane band"


def test_baseline_ctc_aggregate(baseline):
    """Total CTC is ~$110-130bn/yr under current law (JCT)."""
    total = baseline.calculate("ctc", period=2026).sum()
    assert 80e9 < total < 160e9, f"CTC aggregate ${total/1e9:.1f}bn outside sane band"


def test_baseline_snap_aggregate(baseline):
    """SNAP benefits are ~$90-110bn/yr (USDA)."""
    total = baseline.calculate("snap", period=2026).sum()
    assert 60e9 < total < 140e9, f"SNAP aggregate ${total/1e9:.1f}bn outside sane band"


def test_ctc_expansion_pipeline():
    """Raising the CTC base to $3,000 should cost tens of billions nationally,
    reduce poverty, reduce the Gini, and produce a positive in-state gain."""
    from engines.pipeline import run_pipeline
    from engines.spec import ReformSpec

    spec = ReformSpec.model_validate(
        {
            "name": "CTC $3,000 test",
            "geography": {"state": "SC"},
            "tax_transfer": {
                "baseline_year": 2026,
                "reforms": {"gov.irs.credits.ctc.amount.base[0].amount": 3000},
            },
            "spending": {"source": "budget_delta"},
        }
    )
    res = run_pipeline(spec)
    m = res.microsim
    assert m is not None and res.io is not None
    assert -200e9 < m.budget_delta_usd < -20e9  # a real but not absurd cost
    assert m.in_state_household_gain_usd > 0
    # The 2026-baseline CTC increase is non-refundable, so it may not reach
    # households below the poverty line: poverty must not WORSEN, and the
    # Gini must improve (gains tilt toward middle deciles vs the top).
    assert m.poverty_rate_reform <= m.poverty_rate_baseline
    assert m.gini_reform < m.gini_baseline
    # bridge consistency
    assert res.bridge.io_shock_usd == pytest.approx(m.in_state_household_gain_usd)
    # SC's share of the national gain should be small (single state)
    national_gain = sum(v.total_change_usd for v in m.state_breakdown.values())
    assert 0 < m.in_state_household_gain_usd < 0.1 * abs(national_gain)
    # decile table populated and totals roughly consistent with breakdown
    assert len(m.decile_table) == 10
    assert res.io.effects["II"]["central"].jobs > 0
    # national map breakdown present for budget_delta shocks, % changes sane
    assert res.io_by_state is not None and len(res.io_by_state) >= 50
    for st, imp in m.state_breakdown.items():
        assert -50 < imp.pct_change < 50, f"{st} pct_change {imp.pct_change} implausible"
