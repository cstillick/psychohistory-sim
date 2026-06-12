"""Reform-spec schema validation tests."""
import pytest
from pydantic import ValidationError

from engines.spec import ReformSpec


def valid_spec(**overrides):
    base = {
        "name": "test",
        "geography": {"state": "SC"},
        "tax_transfer": {"baseline_year": 2026, "reforms": {"gov.x.y": 1}},
        "spending": {"source": "budget_delta"},
    }
    base.update(overrides)
    return base


def test_valid_spec_parses():
    spec = ReformSpec.model_validate(valid_spec())
    assert spec.geography.state == "SC"
    assert spec.options.multiplier_types == ["I", "II"]


def test_lowercase_state_normalized():
    spec = ReformSpec.model_validate(valid_spec(geography={"state": "ok"}))
    assert spec.geography.state == "OK"


def test_unknown_state_rejected():
    with pytest.raises(ValidationError):
        ReformSpec.model_validate(valid_spec(geography={"state": "ZZ"}))


def test_empty_reforms_rejected():
    with pytest.raises(ValidationError):
        ReformSpec.model_validate(
            valid_spec(tax_transfer={"baseline_year": 2026, "reforms": {}})
        )


def test_budget_delta_requires_tax_transfer():
    bad = valid_spec()
    bad.pop("tax_transfer")
    with pytest.raises((ValidationError, ValueError)):
        ReformSpec.model_validate(bad)


def test_explicit_program_requires_items():
    with pytest.raises(ValidationError):
        ReformSpec.model_validate(
            valid_spec(spending={"source": "explicit_program", "explicit_program": []})
        )


def test_at_least_one_engine_required():
    with pytest.raises((ValidationError, ValueError)):
        ReformSpec.model_validate({"name": "x", "geography": {"state": "SC"}})
