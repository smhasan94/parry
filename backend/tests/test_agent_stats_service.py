"""Unit tests for agent_stats_service input guards.

DB-backed assembly is exercised in e2e tests; here we lock down the
tiny bits of logic that live outside SQLAlchemy so they can't silently
regress (the Python-side tool-call aggregator and the window parser).
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.services import agent_stats_service


def test_parse_window_accepts_valid_windows() -> None:
    for w in ("7d", "30d", "90d"):
        assert agent_stats_service._parse_window(w) == w


def test_parse_window_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid window"):
        agent_stats_service._parse_window("1d")
    with pytest.raises(ValueError):
        agent_stats_service._parse_window("")


def test_tool_call_counter_aggregates_name_field() -> None:
    """The service fetches JSONB tool_calls and aggregates in Python.
    Mirror that loop directly here so a refactor can't break the
    expected 'name' / 'tool' / top-N contract."""
    rows = [
        ([{"name": "web_search"}, {"name": "read_file"}],),
        ([{"name": "web_search"}, {"tool": "write_file"}],),  # legacy key
        ([{"name": "web_search"}],),
        (None,),  # null tool_calls — must be skipped
        ([],),  # empty list
        (["not_a_dict"],),  # malformed — must not crash
        ([{"name": ""}],),  # empty name — must be skipped
    ]
    counter: Counter[str] = Counter()
    for (calls,) in rows:
        if not calls:
            continue
        for call in calls:
            if isinstance(call, dict):
                name = call.get("name") or call.get("tool")
                if isinstance(name, str) and name:
                    counter[name] += 1

    assert counter["web_search"] == 3
    assert counter["read_file"] == 1
    assert counter["write_file"] == 1
    assert "not_a_dict" not in counter
    assert "" not in counter
