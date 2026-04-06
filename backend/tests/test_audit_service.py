"""Tests for audit_service and Actor dataclass — pure logic only."""
import uuid

from app.core.dependencies import Actor
from app.db.models import AuditLog


class TestActor:
    def test_default_fields(self) -> None:
        actor = Actor(actor_type="system")
        assert actor.actor_type == "system"
        assert actor.actor_id is None
        assert actor.label is None

    def test_user_actor(self) -> None:
        actor = Actor(actor_type="user", actor_id="user_abc", label="alice@example.com")
        assert actor.actor_type == "user"
        assert actor.actor_id == "user_abc"
        assert actor.label == "alice@example.com"

    def test_api_key_actor(self) -> None:
        key_id = str(uuid.uuid4())
        actor = Actor(actor_type="api_key", actor_id=key_id, label="Production SDK")
        assert actor.actor_type == "api_key"
        assert actor.actor_id == key_id
        assert actor.label == "Production SDK"


class TestAuditLogModel:
    def test_construction_with_required_fields(self) -> None:
        org_id = uuid.uuid4()
        entry = AuditLog(
            org_id=org_id,
            actor_type="user",
            action="incident.acknowledged",
        )
        assert entry.org_id == org_id
        assert entry.actor_type == "user"
        assert entry.action == "incident.acknowledged"
        assert entry.actor_id is None
        assert entry.resource_type is None
        assert entry.details is None

    def test_construction_with_full_fields(self) -> None:
        org_id = uuid.uuid4()
        incident_id = str(uuid.uuid4())
        details = {"previous_status": "open", "new_status": "resolved"}
        entry = AuditLog(
            org_id=org_id,
            actor_type="user",
            actor_id="user_abc",
            actor_label="alice@example.com",
            action="incident.resolved",
            resource_type="incident",
            resource_id=incident_id,
            details=details,
        )
        assert entry.actor_label == "alice@example.com"
        assert entry.resource_type == "incident"
        assert entry.resource_id == incident_id
        assert entry.details == details

    def test_action_naming_convention(self) -> None:
        """Audit actions follow 'resource.verb' convention for consistent filtering."""
        for action in (
            "incident.acknowledged",
            "incident.resolved",
            "incident.dismissed",
            "api_key.created",
            "api_key.revoked",
        ):
            assert "." in action, f"action '{action}' must contain a dot separator"
            resource, verb = action.split(".", 1)
            assert resource and verb
