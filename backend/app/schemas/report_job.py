"""Response schema for the async compliance-report job endpoints."""

from __future__ import annotations

from app.schemas.base import ParrySchema


class ReportJobStatusResponse(ParrySchema):
    job_id: str
    status: str  # queued|running|completed|failed
    download_url: str | None = None
