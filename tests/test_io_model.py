"""I-O engine tests: exact hand-checked Leontief math on a tiny fake economy,
plus plausibility checks on the real regionalized model (network required;
data is cached after the first run)."""
import numpy as np
import pytest

from engines.io_model import RegionalIOModel, SCENARIOS, match_industry


def make_fake_model() -> RegionalIOModel:
    """Two-industry textbook economy with no import/LQ adjustment, so the
    engine's output must equal the hand-computed Leontief inverse."""
    m = RegionalIOModel.__new__(RegionalIOModel)
    m.state = "XX"
    m.sectors = ["a", "b"]
    m.sector_names = {"a": "Industry A", "b": "Industry B"}
    m.A_nat = np.array([[0.2, 0.3], [0.4, 0.1]])
    m.comp_row = np.array([0.3, 0.4])
    m.domestic_share = np.array([1.0, 1.0])
    m.pce_share = np.array([0.5, 0.5])
    m.gross_output_usd = np.array([1e9, 1e9])
    m.emp_nat = np.array([10_000.0, 10_000.0])
    m.emp_state = np.array([1_000.0, 1_000.0])
    m.slq = np.array([1.0, 1.0])
    m.wage_ratio = np.array([1.0, 1.0])
    m.jobs_per_usd_nat = m.emp_nat / m.gross_output_usd
    return m


def test_leontief_hand_check_type_i():
    """A = [[.2,.3],[.4,.1]] -> (I-A)^-1 column-1 sum = 13/6 (hand-computed)."""
    model = make_fake_model()
    res = model.run_shock(
        spending_by_sector={"a": 1_000_000.0},
        shock_kind="industry_spending",
        shock_total_usd=1_000_000.0,
        scenarios=["central"],
        multiplier_types=["I"],
    )
    eff = res.effects["I"]["central"]
    # det(I-A) = 0.8*0.9 - 0.3*0.4 = 0.6; L = [[1.5, .5],[2/3, 4/3]]
    assert eff.output_multiplier == pytest.approx(13 / 6, rel=1e-9)
    assert eff.output_usd == pytest.approx(1_000_000 * 13 / 6, rel=1e-9)
    # earnings = h . dX = 0.3*1.5e6 + 0.4*(2/3)e6
    assert eff.earnings_usd == pytest.approx(0.3 * 1.5e6 + 0.4 * (2 / 3) * 1e6, rel=1e-9)
    # jobs = 1e-5 jobs/$ * total output
    assert eff.jobs == pytest.approx(1e-5 * 1_000_000 * 13 / 6, rel=1e-9)


def test_type_ii_exceeds_type_i_and_matches_closed_inverse():
    model = make_fake_model()
    res = model.run_shock(
        spending_by_sector={"a": 1_000_000.0},
        shock_kind="industry_spending",
        shock_total_usd=1_000_000.0,
        scenarios=["central"],
        multiplier_types=["I", "II"],
    )
    t1 = res.effects["I"]["central"].output_usd
    t2 = res.effects["II"]["central"].output_usd
    assert t2 > t1
    # Independent computation of the household-closed inverse
    mpc = SCENARIOS["central"]["mpc"]
    A2 = np.zeros((3, 3))
    A2[:2, :2] = model.A_nat
    A2[:2, 2] = mpc * model.pce_share
    A2[2, :2] = model.comp_row
    L2 = np.linalg.inv(np.eye(3) - A2)
    expected = (L2 @ np.array([1_000_000.0, 0.0, 0.0]))[:2].sum()
    assert t2 == pytest.approx(expected, rel=1e-9)


def test_match_industry():
    assert match_industry("Transit and ground passenger transportation") == "48TW"
    assert match_industry("highway construction") == "23"
    assert match_industry("Manufacturing") == "31G"
    assert match_industry("FIRE") == "FIRE"
    with pytest.raises(ValueError):
        match_industry("xyzzy quux")


@pytest.fixture(scope="module")
def sc_model():
    return RegionalIOModel("SC")


def test_real_model_sane(sc_model):
    assert np.all(sc_model.domestic_share > 0) and np.all(sc_model.domestic_share <= 1)
    assert np.all(sc_model.slq >= 0)
    # SC manufacturing is over-represented; SLQ should exceed ~0.9
    i = sc_model.sectors.index("31G")
    assert sc_model.slq[i] > 0.9


def test_real_multiplier_plausible_range(sc_model):
    """Acceptance check: a state-level construction Type II final-demand output
    multiplier should land in the range published RIMS II tables show (~1.5-2.5)."""
    res = sc_model.run_shock(
        spending_by_sector={"23": 100_000_000.0},
        shock_kind="industry_spending",
        shock_total_usd=100_000_000.0,
        scenarios=["low", "central", "high"],
        multiplier_types=["I", "II"],
    )
    m1 = res.effects["I"]["central"].output_multiplier
    m2 = res.effects["II"]["central"].output_multiplier
    assert 1.1 < m1 < 2.0, f"Type I construction multiplier {m1:.2f} out of plausible range"
    assert 1.5 < m2 < 2.5, f"Type II construction multiplier {m2:.2f} out of plausible range"
    assert m2 > m1
    # scenario ordering
    for t in ("I", "II"):
        e = res.effects[t]
        assert e["low"].output_usd <= e["central"].output_usd <= e["high"].output_usd
    # jobs per $1M spent should be sane (construction ~5-20)
    jobs_per_mn = res.effects["II"]["central"].jobs / 100
    assert 3 < jobs_per_mn < 30


def test_bea_parse_real_data_anchors():
    """Regression for the column/row misalignment bug: anchors against the
    actual 2023 BEA Use sheet (network/cached)."""
    from data.fetch import bea_use_aggregates

    use = bea_use_aggregates()
    # Ag industry total output is ~$623.5bn in the 2023 sheet ($mn units);
    # the broken parser produced 348,381 (intermediate inputs only).
    assert 550_000 < use.loc["11", "gross_output"] < 750_000
    # Health/education is ~20% of PCE; the broken parser gave it 0.5%.
    pce_share = use["pce"] / use["pce"].sum()
    assert 0.12 < pce_share["6"] < 0.30
    # Construction is investment, not consumption.
    assert pce_share["23"] == 0.0
    # Manufacturing has heavy import leakage; the broken parser said zero.
    assert use.loc["31G", "domestic_share"] < 0.85
    assert (use["domestic_share"] < 0.999).sum() >= 8
