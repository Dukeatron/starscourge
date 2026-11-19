"""FastAPI routes connecting the UI, the mock company state and the AI compliance engine.

Run:  uvicorn main:app --reload
Bring your own model: each request can carry the user's key in X-LLM-Api-Key (or the
older X-Anthropic-Api-Key), plus optional X-LLM-Provider and X-LLM-Model headers. With a
key but no provider, the provider is detected from the key prefix. Without a key the
server's environment is used. Keys are never logged or stored. Base URLs are server
config only, so callers cannot point the server at arbitrary hosts.
"""

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from ai_engine import (
    PROVIDERS,
    LLMConfigError,
    LLMError,
    LLMSetupError,
    analyze_compliance_gap,
    generate_audit_report as engine_audit_report,
)
from mock_db import get_compliance_state
from models import AuditGenerationRequest, RegulationAnalysisRequest

logger = logging.getLogger("api")

app = FastAPI(title="Compliance Copilot API")

# The UI is served from this app (same origin, no CORS needed). Cross-origin access is
# limited to local dev servers on any port, plus any origins listed in CORS_ALLOW_ORIGINS
# (comma-separated), so an arbitrary website cannot drive this unauthenticated API from a
# visitor's browser.
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
EXTRA_ORIGINS = [o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=EXTRA_ORIGINS,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY_HEADER = "X-LLM-Api-Key"
LEGACY_KEY_HEADER = "X-Anthropic-Api-Key"
PROVIDER_HEADER = "X-LLM-Provider"
MODEL_HEADER = "X-LLM-Model"


def _call_engine(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run an engine function and map its errors to HTTP status codes.

    ValueError -> 422 INVALID_INPUT; missing or rejected key -> 401 LLM_AUTH; server-side
    LLM setup (unknown model, bad LLM_* env) -> 500 LLM_CONFIG; any other LLMError (provider
    down, timeout, unusable output) -> 502 LLM_UNAVAILABLE. Messages never contain keys.
    """
    try:
        return function(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": "INVALID_INPUT", "message": str(exc)})
    except LLMSetupError as exc:
        logger.warning("LLM setup error: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "LLM_CONFIG", "message": str(exc)})
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "LLM_AUTH",
                "message": f"{exc}. Send your key in the {API_KEY_HEADER} header (optionally {PROVIDER_HEADER} and {MODEL_HEADER}).",
            },
        )
    except LLMError as exc:
        logger.warning("engine failure: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail={"error": "LLM_UNAVAILABLE", "message": str(exc)})


def _clean(header_value: Optional[str]) -> Optional[str]:
    if header_value is None or not header_value.strip():
        return None
    return header_value.strip()


def llm_options(
    x_llm_api_key: Optional[str] = Header(None, alias=API_KEY_HEADER),
    x_anthropic_api_key: Optional[str] = Header(None, alias=LEGACY_KEY_HEADER),
    x_llm_provider: Optional[str] = Header(None, alias=PROVIDER_HEADER),
    x_llm_model: Optional[str] = Header(None, alias=MODEL_HEADER),
) -> dict:
    """The caller's LLM choice from request headers, as engine keyword arguments."""
    key = _clean(x_llm_api_key)
    provider = _clean(x_llm_provider)
    if key is None and _clean(x_anthropic_api_key):
        key = _clean(x_anthropic_api_key)
        provider = provider or "anthropic"
    return {"api_key": key, "provider": provider.lower() if provider else None, "model": _clean(x_llm_model)}


STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def index():
    """Serve the single-page frontend."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/providers")
def providers():
    """Providers a caller can choose with the X-LLM-Provider header."""
    return {"providers": list(PROVIDERS)}


@app.get("/api/system-state")
def system_state():
    """Expose the current mock company compliance profile."""
    return get_compliance_state()


@app.post("/api/analyze-regulation")
def analyze_regulation(request: RegulationAnalysisRequest, llm: dict = Depends(llm_options)):
    """Analyze regulation text against the company profile. Returns the list of anomalies."""
    state = request.company_state if request.company_state is not None else get_compliance_state()
    return _call_engine(analyze_compliance_gap, request.text, state, **llm)


@app.post("/api/generate-audit")
def generate_audit_report(request: AuditGenerationRequest, llm: dict = Depends(llm_options)):
    """Generate the Markdown audit log.

    Pass the `anomalies` returned by /api/analyze-regulation to avoid a second analysis;
    otherwise `text` is analyzed first. Returns {"anomalies": [...], "markdown": "...",
    "renderer": "llm" | "deterministic", "model": str | null}.
    """
    anomalies = request.anomalies
    if anomalies is None:
        state = request.company_state if request.company_state is not None else get_compliance_state()
        anomalies = _call_engine(analyze_compliance_gap, request.text, state, **llm)
    report = _call_engine(engine_audit_report, anomalies, **llm)
    # "renderer" and "model" are additive: "llm" | "deterministic", and the model called (or null).
    return {"anomalies": anomalies, "markdown": report["markdown"], "renderer": report["renderer"], "model": report["model"]}
