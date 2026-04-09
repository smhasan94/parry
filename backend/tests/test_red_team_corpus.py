"""Corpus loader + validator tests.

Boots the bundled corpus and asserts the basic invariants:
- All eight categories present
- Every attack has a unique id
- Every expected_detector is a known detector
- Every attack has at least one of prompt/response/tool_calls
"""

from __future__ import annotations

import json

import pytest

from app.detection import red_team_corpus
from app.detection.red_team_corpus import (
    CORPUS_DIR,
    CorpusValidationError,
    _KNOWN_DETECTORS,
    _validate_category,
    category_summary,
    load_corpus,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    load_corpus.cache_clear()
    yield
    load_corpus.cache_clear()


def test_bundled_corpus_loads() -> None:
    attacks = load_corpus()
    assert len(attacks) > 0


def test_all_eight_categories_present() -> None:
    summary = category_summary()
    expected = {
        "instruction_override",
        "jailbreak",
        "data_exfil",
        "tool_hijack",
        "privilege_escalation",
        "content_smuggling",
        "indirect",
        "cost_exploit",
    }
    assert set(summary.keys()) == expected


def test_attacks_have_known_detectors_only() -> None:
    for attack in load_corpus():
        for det in attack["expected_detectors"]:
            assert det in _KNOWN_DETECTORS, (
                f"{attack['id']} references unknown detector {det}"
            )


def test_attack_ids_unique() -> None:
    ids = [a["id"] for a in load_corpus()]
    assert len(ids) == len(set(ids))


def test_every_attack_has_payload() -> None:
    for attack in load_corpus():
        assert (
            attack.get("prompt")
            or attack.get("response")
            or attack.get("tool_calls")
        ), f"{attack['id']} has no payload"


def test_every_corpus_file_validates() -> None:
    for json_file in CORPUS_DIR.glob("*.json"):
        data = json.loads(json_file.read_text())
        _validate_category(data, json_file.name)


def test_validate_rejects_unknown_detector(tmp_path, monkeypatch) -> None:
    bad = {
        "schema_version": "1.0",
        "category": "test",
        "attacks": [
            {
                "id": "x",
                "severity_expected": "high",
                "expected_detectors": ["does_not_exist"],
                "prompt": "hi",
            }
        ],
    }
    with pytest.raises(CorpusValidationError):
        _validate_category(bad, "fake.json")


def test_validate_rejects_missing_payload() -> None:
    bad = {
        "schema_version": "1.0",
        "category": "test",
        "attacks": [
            {
                "id": "x",
                "severity_expected": "high",
                "expected_detectors": ["prompt_injection"],
            }
        ],
    }
    with pytest.raises(CorpusValidationError):
        _validate_category(bad, "fake.json")


def test_validate_rejects_bad_severity() -> None:
    bad = {
        "schema_version": "1.0",
        "category": "test",
        "attacks": [
            {
                "id": "x",
                "severity_expected": "spicy",
                "expected_detectors": ["prompt_injection"],
                "prompt": "hi",
            }
        ],
    }
    with pytest.raises(CorpusValidationError):
        _validate_category(bad, "fake.json")
