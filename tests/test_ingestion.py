"""Ingestion tests that don't need an API key: spec assembly, honesty rails,
and graceful degradation. Live-extraction tests are marked apikey."""
import os

import pytest

from ingestion.extract import (
    Extraction,
    ExtractionFailed,
    IngestionUnavailable,
    Provision,
    build_spec,
    extract_provisions,
)


def prov(**kw):
    base = dict(
        description="test provision",
        mapping_type="unmapped",
        confidence="high",
        rationale="",
        parameter_path=None,
        value=None,
        industry=None,
        amount_usd=None,
    )
    base.update(kw)
    return Provision(**base)


def test_no_api_key_degrades_gracefully(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(IngestionUnavailable, match="ANTHROPIC_API_KEY"):
        extract_provisions("raise the EITC")


def test_nothing_runnable_returns_none():
    ex = Extraction(
        name="regulatory bill",
        state="OK",
        provisions=[prov(description="zoning mandate", rationale="not fiscal")],
    )
    spec, warnings = build_spec(ex)
    assert spec is None
    assert any("Unmapped" in w for w in warnings)


def test_spending_provision_builds_spec():
    ex = Extraction(
        name="transit bill",
        state="OK",
        provisions=[
            prov(
                mapping_type="industry_spending",
                industry="Transit and ground passenger transportation",
                amount_usd=200_000_000,
            )
        ],
    )
    spec, warnings = build_spec(ex)
    assert spec is not None
    assert spec.geography.state == "OK"
    assert spec.spending.source == "explicit_program"
    assert spec.spending.explicit_program[0].amount_usd == 200_000_000
    assert spec.tax_transfer is None


def test_spending_without_state_is_not_run():
    ex = Extraction(
        name="transit bill",
        state=None,
        provisions=[
            prov(mapping_type="industry_spending", industry="transit", amount_usd=1e8)
        ],
    )
    spec, warnings = build_spec(ex)
    assert spec is None
    assert any("need a state" in w for w in warnings)


@pytest.mark.slow
def test_invalid_parameter_path_demoted_to_warning():
    ex = Extraction(
        name="fake param bill",
        state="SC",
        provisions=[
            prov(
                mapping_type="policyengine_parameter",
                parameter_path="gov.made.up.path",
                value=1000,
            ),
            prov(
                mapping_type="policyengine_parameter",
                parameter_path="gov.irs.credits.ctc.amount.base[0].amount",
                value=3000,
            ),
        ],
    )
    spec, warnings = build_spec(ex)
    assert spec is not None
    assert "gov.made.up.path" not in spec.tax_transfer.reforms
    assert spec.tax_transfer.reforms["gov.irs.credits.ctc.amount.base[0].amount"] == 3000
    assert any("gov.made.up.path" in w for w in warnings)
    # state present + tax reform -> budget_delta bridge auto-wired
    assert spec.spending is not None and spec.spending.source == "budget_delta"


@pytest.mark.apikey
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_extraction_plain_english():
    ex = extract_provisions(
        "Raise the federal child tax credit to $3,000 and put $200 million a year into transit in Oklahoma."
    )
    kinds = {p.mapping_type for p in ex.provisions}
    assert "policyengine_parameter" in kinds
    assert "industry_spending" in kinds


def test_mixed_bill_without_state_still_runs_tax_side():
    """A bill with tax provisions AND spending but no state must run the tax
    side nationally — not be falsely refused as 'nothing runnable'."""
    ex = Extraction(
        name="mixed bill",
        state=None,
        provisions=[
            prov(
                mapping_type="industry_spending",
                industry="transit",
                amount_usd=1e8,
            ),
            prov(
                mapping_type="policyengine_parameter",
                parameter_path="gov.irs.credits.ctc.amount.base[0].amount",
                value=3000,
            ),
        ],
    )
    spec, warnings = build_spec(ex)
    assert spec is not None
    assert spec.geography.state == "US"
    assert spec.tax_transfer is not None
    assert spec.spending is None  # spending dropped with a warning, not fabricated
    assert any("need a state" in w for w in warnings)


def test_truncated_input_is_disclosed():
    ex = Extraction(name="t", state="OK", provisions=[], truncated=True)
    spec, warnings = build_spec(ex)
    assert spec is None
    assert any("truncated" in w for w in warnings)
