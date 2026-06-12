"""API surface tests (fast — pipeline mocked where heavy)."""
import json

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
from api.app import app
from engines.pipeline import Bridge, SimulationResult
from engines.spec import ReformSpec

client = TestClient(app)


def fake_result(spec: ReformSpec) -> SimulationResult:
    return SimulationResult(
        spec=spec, microsim=None, io=None, io_by_state=None,
        bridge=Bridge(), assumptions=["test"], warnings=[],
    )


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "RESULTS_DIR", tmp_path)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "ai_ingestion" in body


def test_simulate_schema_rejection():
    r = client.post("/simulate", json={"name": "bad", "geography": {"state": "ZZ"}})
    assert r.status_code == 422  # pydantic validation


def test_simulate_engine_error_is_readable(monkeypatch):
    def boom(spec):
        raise ValueError("Could not find the parameter gov.bogus")

    monkeypatch.setattr(app_module, "run_pipeline", boom)
    r = client.post(
        "/simulate",
        json={"name": "x", "geography": {"state": "OK"},
              "tax_transfer": {"baseline_year": 2026, "reforms": {"gov.bogus": 1}}},
    )
    assert r.status_code == 422
    assert "gov.bogus" in r.json()["detail"]


def test_simulate_caches_by_spec_hash(monkeypatch, tmp_path):
    calls = {"n": 0}

    def counted(spec):
        calls["n"] += 1
        return fake_result(spec)

    monkeypatch.setattr(app_module, "run_pipeline", counted)
    # spending-only spec: skips PolicyEngine path validation, exercising the cache
    body = {"name": "cache me", "geography": {"state": "OK"},
            "spending": {"source": "explicit_program",
                         "explicit_program": [{"industry": "transit", "amount_usd": 1e6}]}}
    r1 = client.post("/simulate", json=body)
    r2 = client.post("/simulate", json=body)
    assert r1.status_code == r2.status_code == 200
    assert calls["n"] == 1, "second identical request must be served from cache"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_interpret_without_key_is_503(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/interpret", json={"text": "raise the EITC"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
