"""Structured FRIA (Fundamental Rights Impact Assessment) template.

Based on EU AI Office guidance (2025-Q1) and Council of Europe's FRIA
template. Sections marked ``auto_populated: True`` are filled from DB
data by fria_service; the rest require user input via the dashboard.
"""

from __future__ import annotations

FRIA_TEMPLATE: dict = {
    "version": "1.0",
    "based_on": "EU AI Office guidance (2025-Q1) + CoE FRIA template",
    "sections": [
        {
            "id": "system_identification",
            "title": "1. System Identification",
            "auto_populated": True,
            "fields": [
                {"key": "system_name", "source": "ai_systems.name"},
                {"key": "intended_purpose", "source": "ai_systems.intended_purpose"},
                {"key": "risk_level", "source": "ai_systems.risk_level"},
                {"key": "annex_iii_cat", "source": "ai_systems.annex_iii_category"},
                {"key": "providers", "source": "ai_system_suppliers"},
                {"key": "deployment_date", "source": "ai_systems.deployment_date"},
                {"key": "deployer", "source": "ai_systems.deployer_name"},
            ],
        },
        {
            "id": "context_of_use",
            "title": "2. Context of Use",
            "auto_populated": False,
            "required": True,
            "fields": [
                {"key": "deployment_environment", "type": "text_long"},
                {"key": "geographic_scope", "type": "text_long"},
                {"key": "user_population", "type": "text_long"},
                {
                    "key": "usage_frequency",
                    "type": "select",
                    "options": ["continuous", "daily", "weekly", "monthly", "ad_hoc"],
                },
                {"key": "data_sources", "type": "text_long"},
            ],
        },
        {
            "id": "affected_populations",
            "title": "3. Affected Populations",
            "auto_populated": False,
            "required": True,
            "fields": [
                {"key": "direct_subjects", "type": "text_long"},
                {"key": "indirect_affected", "type": "text_long"},
                {"key": "vulnerable_groups", "type": "text_long"},
                {"key": "population_size", "type": "text_short"},
            ],
        },
        {
            "id": "impacts",
            "title": "4. Potential Impacts on Fundamental Rights",
            "auto_populated": False,
            "required": True,
            "fields": [
                {"key": "dignity", "type": "text_long"},
                {"key": "privacy", "type": "text_long"},
                {"key": "data_protection", "type": "text_long"},
                {"key": "non_discrimination", "type": "text_long"},
                {"key": "freedom_of_expression", "type": "text_long"},
                {"key": "due_process", "type": "text_long"},
                {"key": "consumer_protection", "type": "text_long"},
                {"key": "workers_rights", "type": "text_long"},
            ],
        },
        {
            "id": "mitigation_measures",
            "title": "5. Mitigation Measures",
            "auto_populated": True,
            "fields": [
                {"key": "policies", "source": "org.policies"},
                {"key": "custom_rules", "source": "org.detector_config.custom_rules"},
                {"key": "detector_config", "source": "org.detector_config"},
                {"key": "alert_channels", "source": "org.alert_config"},
                {"key": "human_oversight_rbac", "source": "computed"},
                {"key": "blocking_enabled", "source": "org.blocking_enabled"},
            ],
        },
        {
            "id": "monitoring_plan",
            "title": "6. Monitoring Plan",
            "auto_populated": True,
            "fields": [
                {"key": "audit_log_retention", "source": "computed"},
                {"key": "incident_workflow", "source": "computed"},
                {"key": "reporting_channels", "source": "org.alert_config"},
                {"key": "review_cadence", "type": "text_short", "required": True},
            ],
        },
        {
            "id": "residual_risk",
            "title": "7. Residual Risk Assessment",
            "auto_populated": False,
            "required": True,
            "fields": [
                {"key": "accepted_risks", "type": "text_long"},
                {"key": "risk_owner", "type": "text_short"},
                {"key": "acceptance_date", "type": "date"},
                {"key": "review_date", "type": "date"},
            ],
        },
        {
            "id": "approval",
            "title": "8. Approval and Sign-off",
            "auto_populated": False,
            "required": True,
            "fields": [
                {"key": "compliance_officer_name", "type": "text_short"},
                {"key": "compliance_officer_title", "type": "text_short"},
                {"key": "approval_date", "type": "date"},
                {"key": "next_review_date", "type": "date"},
                {
                    "key": "signature_method",
                    "type": "select",
                    "options": ["manual", "digital", "wet_ink"],
                },
            ],
        },
    ],
}
