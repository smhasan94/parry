"""Loader + validator for the bundled red-team attack corpus.

The corpus lives as JSON files under ``red_team_corpus/`` — one file
per category. The loader reads + validates them once at first call,
caches the flat list in memory, and hands it back on every subsequent
call. The cache is process-local; Celery workers and the API process
each warm it once.

Schema for a category file::

    {
      "schema_version": "1.0",
      "category": "instruction_override",
      "attacks": [
        {
          "id": "io_001_ignore_all_previous",
          "severity_expected": "high",
          "prompt": "...",
          "response": null,
          "tool_calls": null,
          "target": "prompt",
          "expected_detectors": ["prompt_injection"],
          "expected_confidence_min": 0.6,
          "source": "Perez & Ribeiro 2022",
          "tags": ["classic"]
        }
      ]
    }

Validation runs at import time so a corrupt file fails the worker
boot loud rather than producing silently bad reports.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CORPUS_DIR = Path(__file__).parent / "red_team_corpus"

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}
_REQUIRED_ATTACK_FIELDS = {"id", "severity_expected", "expected_detectors"}
_KNOWN_DETECTORS = {
    "prompt_injection",
    "indirect_injection",
    "jailbreak",
    "privilege_escalation",
    "tool_misuse",
    "data_exfiltration",
    "anomaly",
    "custom_rules",
    "llm_fallback",
    "mcp_manifest",
}


class CorpusValidationError(ValueError):
    pass


def _validate_category(data: dict[str, Any], filename: str) -> None:
    if data.get("schema_version") != "1.0":
        raise CorpusValidationError(f"{filename}: missing or unknown schema_version")
    category = data.get("category")
    if not isinstance(category, str) or not category:
        raise CorpusValidationError(f"{filename}: missing category")
    attacks = data.get("attacks")
    if not isinstance(attacks, list) or not attacks:
        raise CorpusValidationError(f"{filename}: attacks must be a non-empty list")

    for attack in attacks:
        missing = _REQUIRED_ATTACK_FIELDS - set(attack.keys())
        if missing:
            raise CorpusValidationError(
                f"{filename}: attack {attack.get('id')} missing fields {missing}"
            )
        if attack["severity_expected"] not in _VALID_SEVERITIES:
            raise CorpusValidationError(
                f"{filename}: attack {attack['id']} bad severity"
            )
        for det in attack["expected_detectors"]:
            if det not in _KNOWN_DETECTORS:
                raise CorpusValidationError(
                    f"{filename}: attack {attack['id']} references unknown detector {det}"
                )
        if not (attack.get("prompt") or attack.get("response") or attack.get("tool_calls")):
            raise CorpusValidationError(
                f"{filename}: attack {attack['id']} has no prompt/response/tool_calls"
            )


def _check_dedup(attacks: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for a in attacks:
        if a["id"] in seen:
            raise CorpusValidationError(f"duplicate attack id: {a['id']}")
        seen.add(a["id"])


@lru_cache(maxsize=1)
def load_corpus() -> list[dict[str, Any]]:
    """Load every category JSON file under ``CORPUS_DIR``.

    Returns a flat list with each attack augmented with its
    ``category`` field. Cached — call ``load_corpus.cache_clear()``
    after editing files in tests.
    """
    if not CORPUS_DIR.exists():
        return []

    attacks: list[dict[str, Any]] = []
    for json_file in sorted(CORPUS_DIR.glob("*.json")):
        data = json.loads(json_file.read_text())
        _validate_category(data, json_file.name)
        for attack in data["attacks"]:
            attack["category"] = data["category"]
            attacks.append(attack)
    _check_dedup(attacks)
    return attacks


def category_summary() -> dict[str, int]:
    """Public-safe view of the corpus: category → attack count.

    Returned by the dashboard's "browse attacks" endpoint. We never
    expose the actual attack prompts via the API — the corpus is
    server-side material and shipping it would help adversaries.
    """
    summary: dict[str, int] = {}
    for attack in load_corpus():
        summary[attack["category"]] = summary.get(attack["category"], 0) + 1
    return summary
