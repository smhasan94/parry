from fastapi import APIRouter

from app.api.v1 import (
    agent_groups,
    agents,
    alerts,
    api_keys,
    audit,
    badges,
    benchmark,
    billing,
    budgets,
    community_rules,
    compliance,
    custom_rules,
    permissions,
    playground,
    scheduled_reports,
    slack,
    threat_intel,
    webhook_endpoints,
    detector_config,
    events,
    incidents,
    mcp,
    metrics_query,
    policies,
    proxy,
    red_team,
    reports,
    sessions,
    slo,
    sso,
    webhooks,
)

api_router = APIRouter()

api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(agent_groups.router, prefix="/agent-groups", tags=["agent-groups"])
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
api_router.include_router(red_team.router, prefix="/red-team", tags=["red-team"])
api_router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(slo.router, prefix="/slo", tags=["slo"])
api_router.include_router(sso.router, prefix="/sso", tags=["sso"])
api_router.include_router(budgets.router, prefix="/budgets", tags=["budgets"])
api_router.include_router(compliance.router, prefix="/compliance", tags=["compliance"])
# Permissions routes are mounted at root level since they span
# /agents/{id}/permissions and /permissions/default
api_router.include_router(permissions.router, tags=["permissions"])
api_router.include_router(
    scheduled_reports.router, prefix="/scheduled-reports", tags=["scheduled-reports"]
)
api_router.include_router(threat_intel.router, prefix="/threat-intel", tags=["threat-intel"])
api_router.include_router(
    webhook_endpoints.router, prefix="/webhooks/endpoints", tags=["webhooks"]
)
api_router.include_router(playground.router, prefix="/playground", tags=["playground"])
api_router.include_router(
    community_rules.router, prefix="/community-rules", tags=["community-rules"]
)
api_router.include_router(slack.router, prefix="/slack", tags=["slack"])
api_router.include_router(badges.router, prefix="/badges", tags=["badges"])
api_router.include_router(benchmark.router, prefix="/benchmark", tags=["benchmark"])
