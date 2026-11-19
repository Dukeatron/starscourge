"""Offline tests for the FastAPI layer. The provider is faked, so no key or network is needed."""

import json

import pytest
from fastapi.testclient import TestClient

import ai_engine
import main
from mock_db import get_compliance_state

client = TestClient(main.app)

REGULATION = ai_engine._DEMO_REGULATION


def finding(**overrides):
    item = {
        "title": "Data retention period too short",
        "category": "data_retention",
        "severity": "high",
        "gap_type": "non_compliant",
        "regulation_requirement": "Retain transaction records for 90 days.",
        "regulation_excerpt": "must retain customer transaction records for a minimum of 90 days",
        "current_state": "data_retention_days = 30",
        "gap_description": "Retention is 30 days, the regulation requires 90.",
        "recommended_remediation": "Raise retention to 90 days.",
    }
    item.update(overrides)
    return item


@pytest.fixture
def fake_provider(monkeypatch):
    calls = []

    def install(*outputs):
        queue = list(outputs)

        def fake(prompt, system_message, json_mode, schema, temperature, max_tokens, *, api_key=None, provider=None, model=None):
            calls.append({"json_mode": json_mode, "api_key": api_key, "prompt": prompt, "provider": provider, "model": model})
            out = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(out, Exception):
                raise out
            return out

        monkeypatch.setattr(ai_engine, "_provider_complete", fake)
        return calls

    return install


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_system_state_returns_mock_profile():
    response = client.get("/api/system-state")
    assert response.status_code == 200
    assert response.json() == get_compliance_state()


def test_analyze_uses_mock_state_and_returns_contract_list(fake_provider):
    calls = fake_provider(json.dumps({"anomalies": [finding(severity="low"), finding(title="No DPO", severity="critical")]}))
    response = client.post("/api/analyze-regulation", json={"text": REGULATION})
    assert response.status_code == 200
    body = response.json()
    assert [a["id"] for a in body] == ["ANOM-001", "ANOM-002"]
    assert body[0]["title"] == "No DPO"
    assert '"data_retention_days": 30' in calls[0]["prompt"]  # mock state was sent
    assert calls[0]["api_key"] is None


def test_analyze_accepts_custom_company_state(fake_provider):
    calls = fake_provider('{"anomalies": []}')
    response = client.post(
        "/api/analyze-regulation", json={"text": REGULATION, "company_state": {"retention_days": 365}}
    )
    assert response.status_code == 200 and response.json() == []
    assert '"retention_days": 365' in calls[0]["prompt"]


def test_byok_header_reaches_the_provider(fake_provider):
    calls = fake_provider('{"anomalies": []}')
    response = client.post(
        "/api/analyze-regulation", json={"text": REGULATION}, headers={"X-Anthropic-Api-Key": " user-key "}
    )
    assert response.status_code == 200
    assert calls[0]["api_key"] == "user-key"


def test_generic_key_provider_and_model_headers(fake_provider):
    calls = fake_provider('{"anomalies": []}')
    response = client.post(
        "/api/analyze-regulation", json={"text": REGULATION},
        headers={"X-LLM-Api-Key": "AIzaSyX", "X-LLM-Provider": "Gemini", "X-LLM-Model": "gemini-2.5-pro"},
    )
    assert response.status_code == 200
    assert calls[0]["api_key"] == "AIzaSyX"
    assert calls[0]["provider"] == "gemini" and calls[0]["model"] == "gemini-2.5-pro"


def test_legacy_anthropic_header_sets_provider(fake_provider):
    calls = fake_provider('{"anomalies": []}')
    client.post("/api/analyze-regulation", json={"text": REGULATION}, headers={"X-Anthropic-Api-Key": "k"})
    assert calls[0]["provider"] == "anthropic"


def test_unknown_provider_header_is_422(fake_provider):
    fake_provider('{"anomalies": []}')
    response = client.post(
        "/api/analyze-regulation", json={"text": REGULATION}, headers={"X-LLM-Provider": "nope"}
    )
    assert response.status_code == 422


def test_providers_endpoint_lists_providers():
    body = client.get("/api/providers").json()
    assert "anthropic" in body["providers"] and "gemini" in body["providers"] and "openai" in body["providers"]


def test_generate_audit_from_text_runs_analysis_then_audit(fake_provider):
    calls = fake_provider(json.dumps({"anomalies": [finding()]}), "not a valid audit log")
    response = client.post("/api/generate-audit", json={"text": REGULATION})
    assert response.status_code == 200
    body = response.json()
    assert body["anomalies"][0]["id"] == "ANOM-001"
    assert body["markdown"].startswith("# Compliance Audit Log")  # fallback renderer
    assert "### ANOM-001" in body["markdown"]
    assert [c["json_mode"] for c in calls] == [True, False, False]


def test_generate_audit_from_anomalies_skips_analysis(fake_provider):
    calls = fake_provider("garbage")
    anomalies = [{"id": "ANOM-001", **finding()}]
    response = client.post("/api/generate-audit", json={"anomalies": anomalies})
    assert response.status_code == 200
    assert response.json()["anomalies"] == anomalies
    assert all(c["json_mode"] is False for c in calls)


def test_generate_audit_empty_anomalies_needs_no_llm(fake_provider):
    calls = fake_provider("unused")
    response = client.post("/api/generate-audit", json={"anomalies": []})
    assert response.status_code == 200
    assert "No compliance gaps detected" in response.json()["markdown"]
    assert calls == []


def test_generate_audit_requires_text_or_anomalies():
    assert client.post("/api/generate-audit", json={}).status_code == 422


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "x" * 100_001}, {"text": 5}])
def test_analyze_rejects_bad_body(body):
    assert client.post("/api/analyze-regulation", json=body).status_code == 422


def test_engine_value_error_maps_to_422(fake_provider):
    fake_provider('{"anomalies": []}')
    response = client.post("/api/analyze-regulation", json={"text": "   ", "company_state": {"a": 1}})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "INVALID_INPUT"


def test_bad_anomaly_shape_maps_to_422(fake_provider):
    fake_provider("unused")
    response = client.post("/api/generate-audit", json={"anomalies": [{"title": "no gap description"}]})
    assert response.status_code == 422


def test_missing_key_maps_to_401(monkeypatch):
    for name in ai_engine.PROVIDERS:
        for var in ai_engine._key_env_vars(name):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    response = client.post("/api/analyze-regulation", json={"text": REGULATION})
    assert response.status_code == 401
    assert "X-LLM-Api-Key" in response.json()["detail"]["message"]


def test_provider_failure_maps_to_502(fake_provider):
    fake_provider(ai_engine.LLMError("provider error: HTTP 529"))
    response = client.post("/api/analyze-regulation", json={"text": REGULATION})
    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "LLM_UNAVAILABLE"


def test_unknown_model_maps_to_500_not_401(fake_provider):
    fake_provider(ai_engine.LLMSetupError("model 'nope' not found at ollama: pull it with `ollama pull nope`"))
    response = client.post("/api/analyze-regulation", json={"text": REGULATION})
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["error"] == "LLM_CONFIG" and "ollama pull nope" in detail["message"]
    assert "X-LLM-Api-Key" not in detail["message"]  # a key would not fix this


def test_bad_server_env_maps_to_500(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")
    response = client.post("/api/analyze-regulation", json={"text": REGULATION})
    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "LLM_CONFIG"


def test_ollama_down_maps_to_502_with_actionable_message(fake_provider):
    fake_provider(ai_engine._connection_error("ollama", RuntimeError(), TimeoutError))
    response = client.post("/api/analyze-regulation", json={"text": REGULATION})
    assert response.status_code == 502
    assert "ollama serve" in response.json()["detail"]["message"]


def test_persistent_bad_output_maps_to_502(fake_provider):
    fake_provider("garbage")
    assert client.post("/api/analyze-regulation", json={"text": REGULATION}).status_code == 502


def test_api_key_is_not_echoed_in_errors(fake_provider):
    fake_provider(ai_engine.LLMConfigError("the API key was rejected by the provider (AuthenticationError)"))
    response = client.post(
        "/api/analyze-regulation", json={"text": REGULATION}, headers={"X-Anthropic-Api-Key": "sk-ant-secret"}
    )
    assert response.status_code == 401
    assert "sk-ant-secret" not in response.text


# --------------------------------------------------------------------------- additive response fields


def test_analyze_response_adds_grounding_and_state_fields(fake_provider):
    fake_provider(json.dumps({"anomalies": [finding(state_fields=["data_retention_days"])]}))
    [a] = client.post("/api/analyze-regulation", json={"text": REGULATION}).json()
    assert {k: a[k] for k in finding()} == {**finding(), "regulation_excerpt": a["regulation_excerpt"]}  # old keys intact
    assert a["state_fields"] == ["data_retention_days"]
    assert a["excerpt_match"] == "exact" and a["excerpt_score"] == 1.0
    start, end = a["excerpt_span"]
    assert REGULATION[start:end] == a["regulation_excerpt"]


def test_generate_audit_response_adds_renderer_and_model(fake_provider):
    fake_provider("not a valid audit log")
    anomalies = [{"id": "ANOM-001", **finding()}]
    body = client.post(
        "/api/generate-audit", json={"anomalies": anomalies}, headers={"X-LLM-Provider": "groq", "X-LLM-Model": "llama-x"}
    ).json()
    assert set(body) == {"anomalies", "markdown", "renderer", "model"}
    assert (body["renderer"], body["model"]) == ("deterministic", "llama-x")

    empty = client.post("/api/generate-audit", json={"anomalies": []}).json()
    assert (empty["renderer"], empty["model"]) == ("deterministic", None)


# --------------------------------------------------------------------------- offline demo mode


def test_demo_mode_runs_the_ui_sample_offline(fake_provider, monkeypatch):
    import demo_fixtures

    calls = fake_provider(AssertionError("demo mode must not call a provider"))
    monkeypatch.setenv("AI_ENGINE_DEMO", "1")
    response = client.post(
        "/api/analyze-regulation",
        json={"text": "  " + demo_fixtures.UI_SAMPLE_REGULATION.replace("\n", "\r\n"), "company_state": get_compliance_state()},
    )
    assert response.status_code == 200
    anomalies = response.json()
    assert [a["id"] for a in anomalies] == ["ANOM-001", "ANOM-002", "ANOM-003", "ANOM-004"]
    assert all(set(a) == set(finding()) | {"id", "state_fields", "excerpt_match", "excerpt_score", "excerpt_span"} for a in anomalies)
    assert all(a["regulation_excerpt"] in demo_fixtures.UI_SAMPLE_REGULATION for a in anomalies)

    audit = client.post("/api/generate-audit", json={"anomalies": anomalies})
    assert audit.status_code == 200
    markdown = audit.json()["markdown"]
    assert demo_fixtures.DEMO_MODEL_LABEL in markdown and "### ANOM-004" in markdown
    assert calls == []


def test_demo_mode_refuses_input_it_has_no_recording_for(fake_provider, monkeypatch):
    calls = fake_provider(AssertionError("demo mode must not call a provider"))
    monkeypatch.setenv("AI_ENGINE_DEMO", "1")
    edited_state = {**get_compliance_state(), "data_retention_days": 365}
    for body in ({"text": REGULATION}, {"text": "Some other regulation text.", "company_state": edited_state}):
        response = client.post("/api/analyze-regulation", json=body)
        assert response.status_code == 502
        assert "AI_ENGINE_DEMO" in response.json()["detail"]["message"]
    assert calls == []


def test_demo_fixture_matches_the_ui_sample_regulation():
    """If the UI's sample text changes, demo_fixtures.UI_SAMPLE_REGULATION must follow it."""
    import re
    from pathlib import Path

    import demo_fixtures

    html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const SAMPLE = `(.*?)`;", html, re.DOTALL)
    if match is None:
        pytest.skip("the UI no longer defines a SAMPLE regulation")
    assert " ".join(match.group(1).split()) == " ".join(demo_fixtures.UI_SAMPLE_REGULATION.split()), (
        "static/index.html SAMPLE changed: update demo_fixtures.UI_SAMPLE_REGULATION and its findings"
    )


def test_cors_allows_the_key_header():
    response = client.options(
        "/api/analyze-regulation",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-llm-api-key,x-llm-provider,x-llm-model,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def _preflight(origin):
    return client.options(
        "/api/analyze-regulation",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "x-llm-api-key,content-type"},
    )


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8000", "http://localhost", "https://localhost:3000"])
def test_cors_allows_local_origins(origin):
    response = _preflight(origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://localhost.evil.example", "http://127.0.0.1.evil.example:80", "null"]
)
def test_cors_rejects_other_origins(origin):
    response = _preflight(origin)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    simple = client.get("/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in simple.headers
