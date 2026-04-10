"""Tests for webhook dispatch service — HMAC signing, event type validation, models."""

import uuid

from app.db.models import Plan, WebhookDelivery, WebhookEndpoint
from app.services.plan_service import PLAN_LIMITS
from app.services.webhook_dispatch_service import (
    MAX_FAILURE_COUNT,
    VALID_EVENT_TYPES,
    compute_signature,
    generate_secret,
    verify_signature,
)


class TestHMACSigning:
    def test_signature_deterministic(self) -> None:
        sig1 = compute_signature('{"event": "test"}', "whsec_abc123")
        sig2 = compute_signature('{"event": "test"}', "whsec_abc123")
        assert sig1 == sig2

    def test_different_payload_different_signature(self) -> None:
        sig1 = compute_signature('{"event": "test1"}', "whsec_abc123")
        sig2 = compute_signature('{"event": "test2"}', "whsec_abc123")
        assert sig1 != sig2

    def test_different_secret_different_signature(self) -> None:
        sig1 = compute_signature('{"event": "test"}', "secret_a")
        sig2 = compute_signature('{"event": "test"}', "secret_b")
        assert sig1 != sig2

    def test_verify_valid_signature(self) -> None:
        payload = '{"data": "hello"}'
        secret = "whsec_test123"
        sig = compute_signature(payload, secret)
        assert verify_signature(payload, secret, sig) is True

    def test_verify_invalid_signature(self) -> None:
        assert verify_signature('{"data": "hello"}', "secret", "wrong_sig") is False

    def test_signature_is_hex(self) -> None:
        sig = compute_signature("test", "secret")
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)


class TestSecretGeneration:
    def test_has_prefix(self) -> None:
        secret = generate_secret()
        assert secret.startswith("whsec_")

    def test_sufficient_length(self) -> None:
        secret = generate_secret()
        assert len(secret) > 40

    def test_unique(self) -> None:
        s1 = generate_secret()
        s2 = generate_secret()
        assert s1 != s2


class TestValidEventTypes:
    def test_detection_triggered(self) -> None:
        assert "detection.triggered" in VALID_EVENT_TYPES

    def test_incident_created(self) -> None:
        assert "incident.created" in VALID_EVENT_TYPES

    def test_incident_resolved(self) -> None:
        assert "incident.resolved" in VALID_EVENT_TYPES

    def test_permission_denied(self) -> None:
        assert "permission.denied" in VALID_EVENT_TYPES

    def test_threat_intel_match(self) -> None:
        assert "threat_intel.match" in VALID_EVENT_TYPES

    def test_budget_exceeded(self) -> None:
        assert "budget.exceeded" in VALID_EVENT_TYPES

    def test_agent_created(self) -> None:
        assert "agent.created" in VALID_EVENT_TYPES

    def test_no_unknown_events(self) -> None:
        assert "unknown.event" not in VALID_EVENT_TYPES


class TestConstants:
    def test_max_failure_count(self) -> None:
        assert MAX_FAILURE_COUNT == 10


class TestWebhookModels:
    def test_endpoint_construction(self) -> None:
        ep = WebhookEndpoint(
            org_id=uuid.uuid4(),
            url="https://example.com/webhook",
            secret="whsec_test",
            event_types=["detection.triggered", "incident.created"],
        )
        assert ep.url == "https://example.com/webhook"
        assert len(ep.event_types) == 2
        assert ep.secret == "whsec_test"

    def test_delivery_construction(self) -> None:
        d = WebhookDelivery(
            endpoint_id=uuid.uuid4(),
            event_type="detection.triggered",
            payload={"detector": "prompt_injection", "severity": "high"},
            status_code=200,
        )
        assert d.event_type == "detection.triggered"
        assert d.status_code == 200
        assert d.error is None


class TestWebhookFeatureGate:
    def test_growth_has_webhooks(self) -> None:
        assert PLAN_LIMITS[Plan.GROWTH]["webhook_subscriptions"] is True

    def test_free_lacks_webhooks(self) -> None:
        assert PLAN_LIMITS[Plan.FREE]["webhook_subscriptions"] is False
