"""Request schemas for the Compliance Copilot API."""

from pydantic import BaseModel, Field


class RegulationAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Regulation text to analyze")


class AuditGenerationRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Regulation text for the audit")
