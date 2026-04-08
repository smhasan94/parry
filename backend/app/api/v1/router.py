from fastapi import APIRouter

from app.api.v1 import (
    agents,
    alerts,
    api_keys,
    audit,
    billing,
    custom_rules,
    detector_config,
    events,
    incidents,
    metrics_query,
    policies,
    proxy,
    reports,
    sessions,
    webhooks,
)

api_router = APIRouter()

api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
api_router.include_router(policies.router, prefix="/policies", tags=["policies"])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(audit.router, prefix="/audit-log", tags=["audit"])
api_router.include_router(
    detector_config.router, prefix="/detector-config", tags=["detector-config"]
)
api_router.include_router(custom_rules.router, prefix="/custom-rules", tags=["custom-rules"])
api_router.include_router(metrics_query.router, prefix="/metrics", tags=["metrics"])
api_router.include_router(proxy.router, prefix="/proxy", tags=["proxy"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
