"""Internal SLO status API.

Surfaces the SLOs defined in ``slo_service`` to the dashboard's SLO
page. Admin-only — values come from in-process counters that can be
used to infer traffic patterns. The page is meant for the on-call
person, not end users.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.rbac import Role, require_role
from app.services import slo_service

router = APIRouter()


@router.get("")
async def get_slo_status(
    _: tuple = Depends(require_role(Role.ADMIN)),
) -> dict:
    """Return the current SLO statuses + a one-line caveat for the UI."""
    return {
        "statuses": slo_service.compute_slo_status(),
        "note": (
            "Values are cumulative since process start. For rolling "
            "windows (last 30d, burn rate) scrape /metrics with "
            "Prometheus and compute in Grafana."
        ),
    }
