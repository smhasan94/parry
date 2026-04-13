"""Tests for EU AI Act compliance features — pure logic only.

Covers supplier metadata lookups, posture obligation dataclass,
FRIA template structure, serious incident deadline calculation,
and model construction for the 4 new compliance tables.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.compliance.fria_template import FRIA_TEMPLATE
from app.compliance.supplier_metadata import (
    SUPPLIER_METADATA,
    get_supplier_info,
    supplier_name_for_model,
)
from app.db.models import (
    AISystem,
    AISystemSupplier,
    FRIADocument,
    SeriousIncident,
)
from app.services.compliance_posture_service import Obligation, overall_status
from app.services.serious_incident_service import days_remaining

# ── Supplier Metadata ───────────────────────────────────────────


class TestSupplierMetadata:
    def test_known_model_exact_match(self) -> None:
        info = get_supplier_info("gpt-4o")
        assert info is not None
        assert info.supplier_name == "OpenAI"
        assert info.jurisdiction == "US"
        assert info.provider_url == "https://openai.com"

    def test_known_model_anthropic(self) -> None:
        info = get_supplier_info("claude-sonnet-4-6")
        assert info is not None
        assert info.supplier_name == "Anthropic"

    def test_prefix_match(self) -> None:
        info = get_supplier_info("gpt-4o-2024-08-06")
        assert info is not None
        assert info.supplier_name == "OpenAI"

    def test_unknown_model_returns_none(self) -> None:
        assert get_supplier_info("totally-unknown-model") is None

    def test_supplier_name_for_known(self) -> None:
        assert supplier_name_for_model("gpt-4o") == "OpenAI"

    def test_supplier_name_for_unknown(self) -> None:
        assert supplier_name_for_model("unknown-model") == "Unknown"

    def test_mistral_models_mapped(self) -> None:
        info = get_supplier_info("mistral-large-latest")
        assert info is not None
        assert info.supplier_name == "Mistral AI"
        assert info.jurisdiction == "FR"

    def test_google_models_mapped(self) -> None:
        info = get_supplier_info("gemini-2.5-pro")
        assert info is not None
        assert info.supplier_name == "Google"

    def test_all_entries_have_required_fields(self) -> None:
        for model_id, info in SUPPLIER_METADATA.items():
            assert info.supplier_name, f"Missing supplier_name for {model_id}"
            assert info.jurisdiction, f"Missing jurisdiction for {model_id}"
            assert info.provider_url, f"Missing provider_url for {model_id}"


# ── FRIA Template ───────────────────────────────────────────────


class TestFRIATemplate:
    def test_template_has_version(self) -> None:
        assert "version" in FRIA_TEMPLATE
        assert FRIA_TEMPLATE["version"] == "1.0"

    def test_template_has_8_sections(self) -> None:
        assert len(FRIA_TEMPLATE["sections"]) == 8

    def test_section_ids_unique(self) -> None:
        ids = [s["id"] for s in FRIA_TEMPLATE["sections"]]
        assert len(ids) == len(set(ids))

    def test_auto_populated_sections_fields_have_source_or_type(self) -> None:
        """Auto-populated sections may contain mixed fields (some user-fill)."""
        for section in FRIA_TEMPLATE["sections"]:
            if section.get("auto_populated"):
                for field in section["fields"]:
                    assert "source" in field or "type" in field, (
                        f"Field {field['key']} in {section['id']} "
                        "missing both 'source' and 'type'"
                    )

    def test_user_fill_sections_have_type(self) -> None:
        for section in FRIA_TEMPLATE["sections"]:
            if not section.get("auto_populated"):
                for field in section["fields"]:
                    if "source" not in field:
                        assert "type" in field, (
                            f"User-fill field {field['key']} in {section['id']} "
                            "missing 'type'"
                        )

    def test_system_identification_is_first(self) -> None:
        assert FRIA_TEMPLATE["sections"][0]["id"] == "system_identification"

    def test_approval_is_last(self) -> None:
        assert FRIA_TEMPLATE["sections"][-1]["id"] == "approval"


# ── Posture Obligations ─────────────────────────────────────────


class TestObligationPosture:
    def test_overall_green(self) -> None:
        obligations = [
            Obligation(id="a", article="26(2)", title="test", status="green"),
            Obligation(id="b", article="26(4)", title="test", status="green"),
        ]
        assert overall_status(obligations) == "green"

    def test_overall_yellow(self) -> None:
        obligations = [
            Obligation(id="a", article="26(2)", title="test", status="green"),
            Obligation(id="b", article="26(5)", title="test", status="yellow"),
        ]
        assert overall_status(obligations) == "yellow"

    def test_overall_red(self) -> None:
        obligations = [
            Obligation(id="a", article="26(2)", title="test", status="green"),
            Obligation(id="b", article="27", title="test", status="red"),
        ]
        assert overall_status(obligations) == "red"

    def test_red_overrides_yellow(self) -> None:
        obligations = [
            Obligation(id="a", article="26(2)", title="test", status="yellow"),
            Obligation(id="b", article="27", title="test", status="red"),
        ]
        assert overall_status(obligations) == "red"

    def test_na_ignored(self) -> None:
        obligations = [
            Obligation(id="a", article="26(2)", title="test", status="green"),
            Obligation(id="b", article="27", title="test", status="na"),
        ]
        assert overall_status(obligations) == "green"

    def test_all_na(self) -> None:
        obligations = [
            Obligation(id="a", article="27", title="test", status="na"),
        ]
        assert overall_status(obligations) == "na"

    def test_empty(self) -> None:
        assert overall_status([]) == "na"

    def test_obligation_with_evidence(self) -> None:
        o = Obligation(
            id="art_26_6",
            article="26(6)",
            title="Usage logs",
            status="green",
            evidence={"audit_log_rows": 100, "minimum_required_days": 180},
            remediation=None,
        )
        assert o.evidence["audit_log_rows"] == 100
        assert o.remediation is None


# ── Serious Incident Deadline ───────────────────────────────────


class TestSeriousIncidentDeadline:
    def test_days_remaining_future(self) -> None:
        report = SeriousIncident(
            org_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            deadline_at=datetime.now(UTC) + timedelta(days=10),
            report_content={},
        )
        remaining = days_remaining(report)
        assert remaining >= 9  # account for time elapsed during test

    def test_days_remaining_past(self) -> None:
        report = SeriousIncident(
            org_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            deadline_at=datetime.now(UTC) - timedelta(days=5),
            report_content={},
        )
        remaining = days_remaining(report)
        assert remaining < 0

    def test_days_remaining_reported(self) -> None:
        report = SeriousIncident(
            org_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            deadline_at=datetime.now(UTC) - timedelta(days=5),
            reported_to_authority_at=datetime.now(UTC),
            report_content={},
        )
        assert days_remaining(report) == 0


# ── Model Construction ──────────────────────────────────────────


class TestComplianceModels:
    def test_ai_system_construction(self) -> None:
        org_id = uuid.uuid4()
        system = AISystem(
            org_id=org_id,
            name="Customer Support AI",
            risk_level="high",
            intended_purpose="Automated customer inquiry routing",
            fria_required=True,
            fria_status="missing",
            agent_ids=[uuid.uuid4()],
        )
        assert system.org_id == org_id
        assert system.risk_level == "high"
        assert system.fria_required is True
        assert len(system.agent_ids) == 1

    def test_ai_system_supplier_construction(self) -> None:
        now = datetime.now(UTC)
        supplier = AISystemSupplier(
            system_id=uuid.uuid4(),
            supplier_name="OpenAI",
            model_id="gpt-4o",
            first_used_at=now - timedelta(days=30),
            last_used_at=now,
            event_count=1500,
            jurisdiction="US",
        )
        assert supplier.supplier_name == "OpenAI"
        assert supplier.event_count == 1500

    def test_fria_document_construction(self) -> None:
        doc = FRIADocument(
            org_id=uuid.uuid4(),
            system_id=uuid.uuid4(),
            version=1,
            status="draft",
            content={"sections": {}},
        )
        assert doc.version == 1
        assert doc.status == "draft"
        assert doc.pdf_bytes is None

    def test_serious_incident_construction(self) -> None:
        now = datetime.now(UTC)
        report = SeriousIncident(
            org_id=uuid.uuid4(),
            incident_id=uuid.uuid4(),
            deadline_at=now + timedelta(days=15),
            report_content={"incident_summary": {"title": "Test"}},
        )
        # report_version uses server_default="1"; Python default is only set at DB level
        assert report.reported_to_authority_at is None
        assert report.report_content["incident_summary"]["title"] == "Test"


# ── Plan Service Feature Gates ──────────────────────────────────


class TestComplianceFeatureGates:
    def test_enterprise_has_all_compliance_features(self) -> None:
        from app.db.models import Plan
        from app.services.plan_service import PLAN_LIMITS

        enterprise = PLAN_LIMITS[Plan.ENTERPRISE]
        assert enterprise["ai_system_register"] is True
        assert enterprise["fria_generator"] is True
        assert enterprise["serious_incident_reporting"] is True
        assert enterprise["compliance_posture"] is True
        assert enterprise["auditor_bundle"] is True

    def test_free_has_no_compliance_features(self) -> None:
        from app.db.models import Plan
        from app.services.plan_service import PLAN_LIMITS

        free = PLAN_LIMITS[Plan.FREE]
        assert free["ai_system_register"] is False
        assert free["fria_generator"] is False
        assert free["serious_incident_reporting"] is False
        assert free["compliance_posture"] is False
        assert free["auditor_bundle"] is False

    def test_pro_has_posture_and_register(self) -> None:
        from app.db.models import Plan
        from app.services.plan_service import PLAN_LIMITS

        pro = PLAN_LIMITS[Plan.PRO]
        assert pro["ai_system_register"] is True
        assert pro["compliance_posture"] is True
        assert pro["fria_generator"] is False
        assert pro["auditor_bundle"] is False
