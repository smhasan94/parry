"""Unit tests for detection_service.

Two surfaces here:

1. ``_merge_policies`` — pure function, easy to test exhaustively.
   The only non-obvious behaviour is that ``max_token_budget`` takes
   the *minimum* across overlapping policies (the strictest cap wins)
   and that the four list fields get deduped.

2. ``run_and_persist_detections`` — the orchestration layer that
   calls the pipeline, persists detections, fires webhooks, and
   creates incidents. Heavily mocked: we patch the pipeline class,
   the webhook + alert dispatchers, the threat-intel Celery task,
   and the baseline auto-compute. The goal is to verify the
   branching, not re-test the pipeline itself (which has its own
   coverage).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Agent, AgentEvent, Org, Policy, Severity
from app.detection.base import DetectionResult
from app.services import detection_service

# ── _merge_policies ───────────────────────────────────────────────


def _policy(
    org_id: uuid.UUID,
    *,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    forbidden_patterns: list[str] | None = None,
    max_token_budget: int | None = None,
) -> Policy:
    return Policy(
        id=uuid.uuid4(),
        org_id=org_id,
        name="p",
        is_active=True,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
        forbidden_patterns=forbidden_patterns,
        max_token_budget=max_token_budget,
    )


def test_merge_policies_with_empty_list_returns_empty_lists() -> None:
    merged = detection_service._merge_policies([])

    assert merged["allowed_tools"] == []
    assert merged["blocked_tools"] == []
    assert merged["allowed_domains"] == []
    assert merged["blocked_domains"] == []
    assert merged["forbidden_patterns"] == []
    assert "max_token_budget" not in merged


def test_merge_policies_concatenates_lists_across_policies() -> None:
    org_id = uuid.uuid4()
    policies = [
        _policy(org_id, allowed_tools=["search", "read"]),
        _policy(org_id, allowed_tools=["write"]),
    ]

    merged = detection_service._merge_policies(policies)

    assert sorted(merged["allowed_tools"]) == ["read", "search", "write"]


def test_merge_policies_deduplicates_overlapping_lists() -> None:
    org_id = uuid.uuid4()
    policies = [
        _policy(org_id, blocked_tools=["exec_code", "shell"]),
        _policy(org_id, blocked_tools=["shell", "rm_rf"]),
    ]

    merged = detection_service._merge_policies(policies)

    # Order isn't guaranteed (set roundtrip) — just check membership + count.
    assert set(merged["blocked_tools"]) == {"exec_code", "shell", "rm_rf"}
    assert len(merged["blocked_tools"]) == 3


def test_merge_policies_takes_minimum_max_token_budget() -> None:
    """The strictest cap wins — a permissive policy can't relax a
    stricter one when both apply."""
    org_id = uuid.uuid4()
    policies = [
        _policy(org_id, max_token_budget=100_000),
        _policy(org_id, max_token_budget=10_000),
        _policy(org_id, max_token_budget=50_000),
    ]

    merged = detection_service._merge_policies(policies)

    assert merged["max_token_budget"] == 10_000


def test_merge_policies_preserves_forbidden_patterns_without_dedup() -> None:
    """Forbidden patterns aren't deduped because identical regexes from
    different policies are still meaningful (different intent / ownership)."""
    org_id = uuid.uuid4()
    policies = [
        _policy(org_id, forbidden_patterns=["secret"]),
        _policy(org_id, forbidden_patterns=["secret", "password"]),
    ]

    merged = detection_service._merge_policies(policies)

    # The list gets concatenated; duplicates are kept.
    assert merged["forbidden_patterns"].count("secret") == 2
    assert "password" in merged["forbidden_patterns"]


# ── run_and_persist_detections: setup helpers ─────────────────────


def _make_agent(org_id: uuid.UUID, baseline: dict[str, Any] | None = None) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        org_id=org_id,
        name="test-agent",
        is_active=True,
        baseline=baseline,
    )


def _make_event(agent_id: uuid.UUID, session_id: uuid.UUID | None = None) -> AgentEvent:
    from datetime import UTC, datetime

    return AgentEvent(
        id=uuid.uuid4(),
        agent_id=agent_id,
        session_id=session_id,
        timestamp=datetime.now(UTC),
        prompt="hello",
        response="hi",
        model="gpt-4o",
        tool_calls=[],
        latency_ms=100,
        token_count=50,
    )


def _make_org(org_id: uuid.UUID) -> Org:
    return Org(
        id=org_id,
        name="Test Org",
        clerk_org_id="clerk_test",
        is_active=True,
    )


def _scalars_returning(rows: list[Any]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _build_pipeline(results: list[DetectionResult], max_severity: Severity | None) -> MagicMock:
    pipeline = MagicMock()
    pipeline.run = AsyncMock(return_value=results)
    pipeline.max_severity = MagicMock(return_value=max_severity)
    return pipeline


def _patch_dispatchers() -> Any:
    """Stub every side-effect dispatcher invoked by run_and_persist_detections."""
    return [
        patch(
            "app.services.webhook_dispatch_service.dispatch_event",
            new_callable=AsyncMock,
        ),
        patch("app.workers.threat_intel_task.extract_threat_pattern", MagicMock()),
        patch(
            "app.services.alert_service.dispatch_incident_alert",
            new_callable=AsyncMock,
        ),
        patch("app.services.baseline_service.compute_baseline", new_callable=AsyncMock),
    ]


# ── run_and_persist_detections ────────────────────────────────────


@pytest.mark.asyncio
async def test_run_and_persist_returns_empty_when_agent_not_found() -> None:
    """If db.get(Agent, ...) returns None we bail before even loading
    policies — the event has no owner so detection isn't meaningful."""
    org_id = uuid.uuid4()
    event = _make_event(uuid.uuid4())
    db = AsyncMock()
    db.get.return_value = None  # Agent missing.

    detections = await detection_service.run_and_persist_detections(db, event)

    assert detections == []
    db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_run_and_persist_creates_detection_rows_for_every_result() -> None:
    """Every pipeline result becomes a Detection row, triggered or not.
    The non-triggered results matter for the dashboard's 'why didn't
    this fire' debugging view."""
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, baseline={"avg_token_count": 50})
    event = _make_event(agent.id)
    org = _make_org(org_id)

    results = [
        DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.1,
            reason="clean",
            detector="prompt_injection",
        ),
        DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.0,
            reason="no policy",
            detector="tool_misuse",
        ),
    ]

    db = AsyncMock()
    db.get.side_effect = [agent, org]
    db.execute.return_value = _scalars_returning([])  # No active policies.

    with patch(
        "app.detection.pipeline.DetectionPipeline",
        return_value=_build_pipeline(results, max_severity=None),
    ):
        with (
            patch(
                "app.services.webhook_dispatch_service.dispatch_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.baseline_service.compute_baseline",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            detections = await detection_service.run_and_persist_detections(db, event)

    assert len(detections) == 2
    # Every result gets persisted regardless of triggered.
    assert db.add.call_count == 2


@pytest.mark.asyncio
async def test_run_and_persist_passes_session_history_to_pipeline() -> None:
    """CostExploitLoopDetector reads event_data["session_history"] and
    bails with "Insufficient session history" when it is missing. Nothing
    used to populate it, so the detector could never fire in production —
    only in its own unit tests, which inject the key by hand. This asserts
    the orchestrator actually loads prior events in the session and hands
    them to the pipeline."""
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, baseline={"avg_token_count": 50})
    event = _make_event(agent.id, session_id=uuid.uuid4())
    org = _make_org(org_id)

    prior = [_make_event(agent.id, session_id=event.session_id) for _ in range(12)]
    for e in prior:
        e.tool_calls = [{"name": "search"}]

    db = AsyncMock()
    db.get.side_effect = [agent, org]
    db.execute.side_effect = [
        _scalars_returning([]),  # active policies
        _scalars_returning(prior),  # session history
    ]

    pipeline = _build_pipeline([], max_severity=None)
    with patch("app.detection.pipeline.DetectionPipeline", return_value=pipeline):
        with (
            patch(
                "app.services.webhook_dispatch_service.dispatch_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.baseline_service.compute_baseline",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await detection_service.run_and_persist_detections(db, event)

    event_data = pipeline.run.await_args.args[0]
    history = event_data["session_history"]
    assert len(history) == 12
    # The detector reads .get("tool_calls") off each entry — dicts, not ORM rows.
    assert all(isinstance(entry, dict) for entry in history)
    assert history[0]["tool_calls"] == [{"name": "search"}]


@pytest.mark.asyncio
async def test_run_and_persist_omits_session_history_for_sessionless_event() -> None:
    """An event with no session_id has no session to reconstruct. Skip the
    query entirely rather than scanning the hypertable for a NULL match."""
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, baseline={"avg_token_count": 50})
    event = _make_event(agent.id)  # session_id is None
    org = _make_org(org_id)

    db = AsyncMock()
    db.get.side_effect = [agent, org]
    db.execute.return_value = _scalars_returning([])  # policies only

    pipeline = _build_pipeline([], max_severity=None)
    with patch("app.detection.pipeline.DetectionPipeline", return_value=pipeline):
        with (
            patch(
                "app.services.webhook_dispatch_service.dispatch_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.baseline_service.compute_baseline",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await detection_service.run_and_persist_detections(db, event)

    event_data = pipeline.run.await_args.args[0]
    assert event_data["session_history"] == []
    # Only the policy query ran — no second round trip for a missing session.
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_loaded_session_history_actually_fires_the_loop_detector() -> None:
    """Contract test across the loader/detector seam.

    The two tests above prove ``session_history`` reaches the pipeline, but
    not that its *shape* is one CostExploitLoopDetector can use — which is
    the thing that was silently wrong. This feeds the real detector the
    real output of ``_load_session_history`` and asserts it fires.

    Guards against a future change to the dict keys, or to
    SESSION_HISTORY_LIMIT dropping below the detector's 10-entry minimum,
    quietly killing the detector again.
    """
    from app.detection.detectors.cost_explosion import CostExploitLoopDetector

    agent_id = uuid.uuid4()
    session_id = uuid.uuid4()
    event = _make_event(agent_id, session_id=session_id)
    event.tool_calls = [{"name": "search"}]

    prior = [_make_event(agent_id, session_id=session_id) for _ in range(15)]
    for e in prior:
        e.tool_calls = [{"name": "search"}]

    db = AsyncMock()
    db.execute.return_value = _scalars_returning(prior)

    history = await detection_service._load_session_history(db, event)

    result = CostExploitLoopDetector().detect(
        {"tool_calls": event.tool_calls, "session_history": history}
    )

    assert result.triggered is True
    assert result.detector == "cost_exploit_loop"


@pytest.mark.asyncio
async def test_run_and_persist_creates_incident_when_any_result_triggers() -> None:
    """A triggered result creates exactly one Incident row that groups
    all triggered detections."""
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, baseline={"avg_token_count": 50})
    event = _make_event(agent.id)
    org = _make_org(org_id)

    results = [
        DetectionResult(
            triggered=True,
            severity=Severity.HIGH,
            confidence=0.9,
            reason="injection",
            detector="prompt_injection",
        ),
        DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.1,
            reason="clean",
            detector="jailbreak",
        ),
    ]

    db = AsyncMock()
    # db.get sequence: agent for pipeline setup, org for detector_config,
    # org again for alert dispatch.
    db.get.side_effect = [agent, org, org]
    db.execute.return_value = _scalars_returning([])

    with patch(
        "app.detection.pipeline.DetectionPipeline",
        return_value=_build_pipeline(results, max_severity=Severity.HIGH),
    ):
        with (
            patch(
                "app.services.webhook_dispatch_service.dispatch_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.alert_service.dispatch_incident_alert",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workers.threat_intel_task.extract_threat_pattern",
                MagicMock(),
            ),
            patch(
                "app.services.baseline_service.compute_baseline",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            detections = await detection_service.run_and_persist_detections(db, event)

    # 2 detections + 1 incident = 3 added rows. The incident is the
    # last add() because it's created after both detections.
    assert db.add.call_count == 3


@pytest.mark.asyncio
async def test_run_and_persist_skips_incident_when_no_result_triggers() -> None:
    """All-clean events don't open an incident — that would flood the
    triage queue with noise."""
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, baseline={"avg_token_count": 50})
    event = _make_event(agent.id)
    org = _make_org(org_id)

    results = [
        DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.0,
            reason="clean",
            detector="prompt_injection",
        ),
    ]

    db = AsyncMock()
    db.get.side_effect = [agent, org]
    db.execute.return_value = _scalars_returning([])

    with patch(
        "app.detection.pipeline.DetectionPipeline",
        return_value=_build_pipeline(results, max_severity=None),
    ):
        with (
            patch(
                "app.services.webhook_dispatch_service.dispatch_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.baseline_service.compute_baseline",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await detection_service.run_and_persist_detections(db, event)

    # Just the one Detection row — no Incident.
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_run_and_persist_auto_computes_baseline_when_agent_has_none() -> None:
    """A first-time agent (baseline is None) gets a baseline computed
    after its first detection cycle."""
    org_id = uuid.uuid4()
    agent = _make_agent(org_id, baseline=None)  # No baseline yet.
    event = _make_event(agent.id)
    org = _make_org(org_id)

    results = [
        DetectionResult(
            triggered=False,
            severity=Severity.LOW,
            confidence=0.0,
            reason="clean",
            detector="prompt_injection",
        ),
    ]

    fake_baseline = {"event_count": 5, "avg_token_count": 42}
    db = AsyncMock()
    db.get.side_effect = [agent, org]
    db.execute.return_value = _scalars_returning([])

    with patch(
        "app.detection.pipeline.DetectionPipeline",
        return_value=_build_pipeline(results, max_severity=None),
    ):
        with (
            patch(
                "app.services.webhook_dispatch_service.dispatch_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.baseline_service.compute_baseline",
                new_callable=AsyncMock,
                return_value=fake_baseline,
            ) as mock_baseline,
        ):
            await detection_service.run_and_persist_detections(db, event)

    mock_baseline.assert_awaited_once()
    assert agent.baseline == fake_baseline


@pytest.mark.asyncio
async def test_run_and_persist_skips_baseline_when_agent_already_has_one() -> None:
    """Existing baselines are preserved — they should only update via
    the explicit recompute path, not the detection cycle."""
    org_id = uuid.uuid4()
    existing = {"event_count": 100, "avg_token_count": 200}
    agent = _make_agent(org_id, baseline=existing)
    event = _make_event(agent.id)
    org = _make_org(org_id)

    db = AsyncMock()
    db.get.side_effect = [agent, org]
    db.execute.return_value = _scalars_returning([])

    with patch(
        "app.detection.pipeline.DetectionPipeline",
        return_value=_build_pipeline([], max_severity=None),
    ):
        with (
            patch(
                "app.services.webhook_dispatch_service.dispatch_event",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.baseline_service.compute_baseline",
                new_callable=AsyncMock,
            ) as mock_baseline,
        ):
            await detection_service.run_and_persist_detections(db, event)

    mock_baseline.assert_not_awaited()
    assert agent.baseline == existing


# ── _get_active_policies ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_active_policies_returns_only_active_for_org() -> None:
    """Smoke test the query-and-return shape — the WHERE clause itself
    is built from declarative SQLAlchemy and not introspected here."""
    org_id = uuid.uuid4()
    rows = [
        _policy(org_id, allowed_tools=["search"]),
        _policy(org_id, blocked_tools=["exec"]),
    ]
    db = AsyncMock()
    db.execute.return_value = _scalars_returning(rows)

    result = await detection_service._get_active_policies(db, org_id)

    assert len(result) == 2
    db.execute.assert_called_once()
