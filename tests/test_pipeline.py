"""Pipeline tests. The explicit-program path runs without the microsim (fast);
microsim-path tests live in test_microsim.py (slow, marked)."""
import pytest

from engines.pipeline import run_pipeline
from engines.spec import ReformSpec


def test_explicit_program_end_to_end():
    spec = ReformSpec.model_validate(
        {
            "name": "transit demo",
            "geography": {"state": "OK"},
            "spending": {
                "source": "explicit_program",
                "explicit_program": [
                    {"industry": "transit", "amount_usd": 200_000_000},
                    {"industry": "highway construction", "amount_usd": 50_000_000},
                ],
            },
        }
    )
    res = run_pipeline(spec)
    assert res.microsim is None
    assert res.io is not None
    assert res.bridge.io_shock_usd == pytest.approx(250_000_000)
    assert res.bridge.io_shock_source == "explicit_program"
    assert set(res.io.spending_vector) == {"48TW", "23"}
    assert "I" in res.io.effects and "II" in res.io.effects
    assert res.io.effects["II"]["central"].jobs > 0
    # honesty rails: assumptions must ship with every result
    assert any("OVERSTATE" in a for a in res.io.assumptions)
    assert any("must not be added" in a for a in res.assumptions)


def test_national_geography_rejected_for_io():
    spec = ReformSpec.model_validate(
        {
            "name": "bad",
            "geography": {"state": "US"},
            "spending": {
                "source": "explicit_program",
                "explicit_program": [{"industry": "transit", "amount_usd": 1e6}],
            },
        }
    )
    with pytest.raises(ValueError, match="regional"):
        run_pipeline(spec)


def test_negative_spending_is_a_withdrawal():
    spec = ReformSpec.model_validate(
        {
            "name": "cut",
            "geography": {"state": "OK"},
            "spending": {
                "source": "explicit_program",
                "explicit_program": [{"industry": "education", "amount_usd": -100_000_000}],
            },
        }
    )
    res = run_pipeline(spec)
    assert res.io.effects["II"]["central"].jobs < 0
    assert res.io.effects["II"]["central"].output_usd < 0


def test_weighted_gini_known_values():
    import numpy as np

    from engines.microsim import _weighted_gini

    # Perfect equality -> 0
    assert _weighted_gini(np.array([5.0, 5.0, 5.0]), np.ones(3)) == pytest.approx(0, abs=1e-9)
    # One person has everything -> approaches 1 with population size
    g = _weighted_gini(np.array([0.0] * 999 + [100.0]), np.ones(1000))
    assert 0.99 < g <= 1.0
    # Weights matter: duplicating via weight == duplicating via repetition
    a = _weighted_gini(np.array([1.0, 2.0, 3.0]), np.array([2.0, 1.0, 1.0]))
    b = _weighted_gini(np.array([1.0, 1.0, 2.0, 3.0]), np.ones(4))
    assert a == pytest.approx(b, rel=1e-9)
