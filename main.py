"""FastAPI routes connecting the UI, mock state, and Dev 1 AI functions."""

from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from mock_db import get_compliance_state
from models import AuditGenerationRequest, RegulationAnalysisRequest


app = FastAPI(title="Compliance Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Backend Dev 1 should expose these exact callables from ai_functions.py:
#   analyze_compliance_gap(text, company_state)
#   generate_audit(text, company_state)
try:
    from ai_functions import analyze_compliance_gap, generate_audit
except ImportError:
    analyze_compliance_gap: Optional[Callable[..., Any]] = None
    generate_audit: Optional[Callable[..., Any]] = None


def _require_ai_function(function: Optional[Callable[..., Any]], name: str) -> Callable[..., Any]:
    if function is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"AI integration unavailable: add ai_functions.py with {name} "
                "from Backend Dev 1."
            ),
        )
    return function


@app.get("/api/system-state")
def system_state():
    """Expose the current mock company compliance profile."""
    return get_compliance_state()


@app.post("/api/analyze-regulation")
def analyze_regulation(request: RegulationAnalysisRequest):
    """Analyze supplied regulation text against the company profile."""
    analyzer = _require_ai_function(analyze_compliance_gap, "analyze_compliance_gap")
    return analyzer(request.text, get_compliance_state())


@app.post("/api/generate-audit")
def generate_audit_report(request: AuditGenerationRequest):
    """Generate an audit markdown report for supplied regulation text."""
    generator = _require_ai_function(generate_audit, "generate_audit")
    return generator(request.text, get_compliance_state())
