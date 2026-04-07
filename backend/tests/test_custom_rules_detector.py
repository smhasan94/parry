"""Unit tests for CustomRulesDetector."""
from app.db.models import Severity
from app.detection.detectors.custom_rules import CustomRulesDetector


def _event(prompt: str = "", response: str = "", rules: list[dict] | None = None) -> dict:
    return {
        "prompt": prompt,
        "response": response,
        "detector_config": {"custom_rules": rules or []},
    }


detector = CustomRulesDetector()


def test_no_rules_does_not_trigger():
    result = detector.detect(_event(prompt="hi", rules=[]))
    assert not result.triggered


def test_disabled_rules_ignored():
    rules = [
        {
            "id": "1",
            "name": "Block foo",
            "pattern": "foo",
            "target": "prompt",
            "severity": "high",
            "enabled": False,
        }
    ]
    result = detector.detect(_event(prompt="mentions foo", rules=rules))
    assert not result.triggered


def test_prompt_target_matches():
    rules = [
        {
            "id": "1",
            "name": "Block competitor",
            "pattern": r"(?i)CompetitorA",
            "target": "prompt",
            "severity": "medium",
            "enabled": True,
        }
    ]
    result = detector.detect(_event(prompt="why is CompetitorA better?", rules=rules))
    assert result.triggered
    assert result.severity == Severity.MEDIUM
    assert result.details["matched_rules"][0]["rule"] == "Block competitor"


def test_response_target_matches():
    rules = [
        {
            "id": "1",
            "name": "Block secret leak",
            "pattern": r"hunter2",
            "target": "response",
            "severity": "critical",
            "enabled": True,
        }
    ]
    result = detector.detect(
        _event(prompt="what's the password?", response="hunter2", rules=rules)
    )
    assert result.triggered
    assert result.severity == Severity.CRITICAL


def test_both_target_searches_prompt_and_response():
    rules = [
        {
            "id": "1",
            "name": "PII",
            "pattern": r"\bSSN\b",
            "target": "both",
            "severity": "high",
            "enabled": True,
        }
    ]
    # Match in response only
    result = detector.detect(_event(prompt="tell me", response="your SSN is", rules=rules))
    assert result.triggered
    # Match in prompt only
    result = detector.detect(_event(prompt="share SSN", response="no", rules=rules))
    assert result.triggered


def test_highest_severity_wins():
    rules = [
        {
            "id": "1",
            "name": "mild",
            "pattern": "foo",
            "target": "prompt",
            "severity": "low",
            "enabled": True,
        },
        {
            "id": "2",
            "name": "nuclear",
            "pattern": "bar",
            "target": "prompt",
            "severity": "critical",
            "enabled": True,
        },
    ]
    result = detector.detect(_event(prompt="foo and bar", rules=rules))
    assert result.triggered
    assert result.severity == Severity.CRITICAL
    assert len(result.details["matched_rules"]) == 2


def test_invalid_regex_skipped_not_crashed():
    rules = [
        {
            "id": "1",
            "name": "bad",
            "pattern": "[unclosed",  # invalid regex
            "target": "prompt",
            "severity": "high",
            "enabled": True,
        },
        {
            "id": "2",
            "name": "ok",
            "pattern": "foo",
            "target": "prompt",
            "severity": "medium",
            "enabled": True,
        },
    ]
    # Should not raise, and the valid rule should still match
    result = detector.detect(_event(prompt="foo bar", rules=rules))
    assert result.triggered
    assert result.details["matched_rules"][0]["rule"] == "ok"


def test_case_insensitive_by_default():
    rules = [
        {
            "id": "1",
            "name": "c",
            "pattern": "CompetitorA",
            "target": "prompt",
            "severity": "low",
            "enabled": True,
        }
    ]
    result = detector.detect(_event(prompt="competitora is fine", rules=rules))
    assert result.triggered


def test_unknown_severity_defaults_to_medium():
    rules = [
        {
            "id": "1",
            "name": "x",
            "pattern": "foo",
            "target": "prompt",
            "severity": "catastrophic",  # not a valid Severity
            "enabled": True,
        }
    ]
    result = detector.detect(_event(prompt="foo", rules=rules))
    assert result.triggered
    assert result.severity == Severity.MEDIUM


def test_no_match_when_rules_dont_hit():
    rules = [
        {
            "id": "1",
            "name": "c",
            "pattern": "zzzzz",
            "target": "prompt",
            "severity": "high",
            "enabled": True,
        }
    ]
    result = detector.detect(_event(prompt="hello world", rules=rules))
    assert not result.triggered
