"""Tests for threat intelligence — pattern hashing, normalization, promotion, decay, models."""

import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import Plan, ThreatIndicator, ThreatSighting
from app.services.plan_service import PLAN_LIMITS
from app.services.threat_intel_service import (
    ACTIVE_SCORE_THRESHOLD,
    ARCHIVE_SCORE_THRESHOLD,
    DECAY_FACTOR,
    PROMOTION_THRESHOLD,
    categorize_detector,
    compute_pattern_hash,
    normalize_reason,
    severity_rank,
)


# ── Pattern hashing ─────────────────────────────────────────────


class TestPatternHash:
    def test_deterministic(self) -> None:
        h1 = compute_pattern_hash("prompt_injection", "high", "Instruction override detected")
        h2 = compute_pattern_hash("prompt_injection", "high", "Instruction override detected")
        assert h1 == h2

    def test_different_detectors_produce_different_hashes(self) -> None:
        h1 = compute_pattern_hash("prompt_injection", "high", "test")
        h2 = compute_pattern_hash("jailbreak", "high", "test")
        assert h1 != h2

    def test_different_severities_produce_different_hashes(self) -> None:
        h1 = compute_pattern_hash("prompt_injection", "high", "test")
        h2 = compute_pattern_hash("prompt_injection", "critical", "test")
        assert h1 != h2

    def test_hash_is_64_char_hex(self) -> None:
        h = compute_pattern_hash("prompt_injection", "high", "test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Reason normalization ────────────────────────────────────────


class TestNormalizeReason:
    def test_strips_quoted_strings(self) -> None:
        result = normalize_reason('Found "malicious payload" in prompt')
        assert "malicious payload" not in result
        assert '""' in result

    def test_strips_single_quoted(self) -> None:
        result = normalize_reason("Found 'malicious payload' in prompt")
        assert "malicious payload" not in result

    def test_strips_emails(self) -> None:
        result = normalize_reason("Send data to attacker@evil.com")
        assert "attacker@evil.com" not in result
        assert "<email>" in result

    def test_strips_uuids(self) -> None:
        result = normalize_reason(
            "Agent 550e8400-e29b-41d4-a716-446655440000 compromised"
        )
        assert "550e8400" not in result
        assert "<uuid>" in result

    def test_strips_ips(self) -> None:
        result = normalize_reason("Exfiltrate to 192.168.1.100")
        assert "192.168.1.100" not in result
        assert "<ip>" in result

    def test_strips_long_numbers(self) -> None:
        result = normalize_reason("Token count 123456 exceeded")
        assert "123456" not in result
        assert "<num>" in result

    def test_preserves_short_numbers(self) -> None:
        result = normalize_reason("Found 3 violations")
        assert "3" in result

    def test_lowercases(self) -> None:
        result = normalize_reason("CRITICAL Injection Detected")
        assert result == result.lower()

    def test_collapses_whitespace(self) -> None:
        result = normalize_reason("too   many   spaces")
        assert "  " not in result

    def test_same_attack_different_payload_same_hash(self) -> None:
        r1 = normalize_reason('Injection detected in "DROP TABLE users"')
        r2 = normalize_reason('Injection detected in "SELECT * FROM passwords"')
        assert r1 == r2


# ── Detector categorization ─────────────────────────────────────


class TestCategorizeDetector:
    def test_known_detectors(self) -> None:
        assert categorize_detector("prompt_injection") == "instruction_override"
        assert categorize_detector("jailbreak") == "jailbreak"
        assert categorize_detector("data_exfiltration") == "data_exfil"
        assert categorize_detector("mcp_manifest") == "mcp_injection"
        assert categorize_detector("cost_exploit_loop") == "cost_exploit"

    def test_unknown_detector(self) -> None:
        assert categorize_detector("future_detector") == "unknown"


# ── Severity ranking ────────────────────────────────────────────


class TestSeverityRank:
    def test_ordering(self) -> None:
        assert severity_rank("critical") > severity_rank("high")
        assert severity_rank("high") > severity_rank("medium")
        assert severity_rank("medium") > severity_rank("low")

    def test_unknown(self) -> None:
        assert severity_rank("unknown") == 0


# ── Promotion / decay math ──────────────────────────────────────


class TestPromotionAndDecay:
    def test_promotion_threshold(self) -> None:
        assert PROMOTION_THRESHOLD == 3

    def test_decay_factor(self) -> None:
        assert 0 < DECAY_FACTOR < 1
        # After 14 days: 0.95^14 ≈ 0.488 — roughly halves
        after_14 = DECAY_FACTOR**14
        assert 0.4 < after_14 < 0.6

    def test_active_threshold(self) -> None:
        assert ACTIVE_SCORE_THRESHOLD == 0.3

    def test_archive_threshold(self) -> None:
        assert ARCHIVE_SCORE_THRESHOLD == 0.1
        assert ARCHIVE_SCORE_THRESHOLD < ACTIVE_SCORE_THRESHOLD

    def test_score_decay_sequence(self) -> None:
        score = 1.0
        days_to_drop = 0
        while score >= ACTIVE_SCORE_THRESHOLD:
            score *= DECAY_FACTOR
            days_to_drop += 1
        # Should take ~24 days to drop below 0.3
        assert 20 < days_to_drop < 30


# ── Model construction ──────────────────────────────────────────


class TestThreatModels:
    def test_indicator_construction(self) -> None:
        ind = ThreatIndicator(
            pattern_hash="a" * 64,
            detector_source="prompt_injection",
            category="instruction_override",
            severity="high",
            confidence_avg=0.85,
            sighting_count=5,
            org_count=3,
            score=0.95,
        )
        assert ind.pattern_hash == "a" * 64
        assert ind.org_count == 3
        assert ind.promoted_at is None
        assert ind.archived_at is None

    def test_sighting_construction(self) -> None:
        s = ThreatSighting(
            indicator_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            detection_id=uuid.uuid4(),
        )
        assert s.indicator_id is not None
        assert s.org_id is not None


# ── Feature gate ────────────────────────────────────────────────


class TestThreatIntelFeatureGate:
    def test_growth_has_threat_intel(self) -> None:
        assert PLAN_LIMITS[Plan.GROWTH]["threat_intelligence"] is True

    def test_free_lacks_threat_intel(self) -> None:
        assert PLAN_LIMITS[Plan.FREE]["threat_intelligence"] is False

    def test_enterprise_has_threat_intel(self) -> None:
        assert PLAN_LIMITS[Plan.ENTERPRISE]["threat_intelligence"] is True
