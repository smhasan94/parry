# Agent Baseline Auto-Generation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically compute and persist a behavioral baseline for agents once they have enough events, so the anomaly detector can catch drift.

**Architecture:** Add a `compute_baseline()` function in a new `baseline_service.py` that runs a SQL aggregate query over the agent's recent events. Call it at the end of the detection pipeline (in `detection_service.py`) when the agent has no baseline yet. The baseline is a JSON dict stored on the `Agent.baseline` column (already exists, currently always null).

**Tech Stack:** SQLAlchemy async (aggregate queries), existing Agent model JSONB column

---

### Task 1: Baseline Service — compute_baseline()

**Files:**
- Create: `backend/app/services/baseline_service.py`
- Test: `backend/tests/test_baseline_service.py`

**Step 1: Write tests for baseline computation**

Test cases:
1. With 20+ events: returns correct baseline dict with avg/std for tokens, latency, tool calls, and known models
2. With <20 events: returns None (not enough data)
3. With events that have null token_count/latency: handles gracefully

**Step 2: Run tests — verify they fail**

Run: `cd backend && uv run pytest tests/test_baseline_service.py -v`

**Step 3: Implement compute_baseline()**

The function:
- Takes `db: AsyncSession` and `agent_id: UUID`
- Counts events for the agent; if < 20, returns None
- Runs aggregate query: AVG/STDDEV of token_count, latency_ms; AVG of tool call count; ARRAY_AGG(DISTINCT model)
- Returns baseline dict matching the shape the anomaly detector expects:
  ```python
  {
      "avg_token_count": float,
      "std_token_count": float,
      "avg_latency_ms": float,
      "std_latency_ms": float,
      "avg_tool_calls": float,
      "known_models": list[str],
      "event_count": int,
      "computed_at": ISO-8601 string,
  }
  ```

**Step 4: Run tests — verify they pass**

**Step 5: Commit**

---

### Task 2: Integration — trigger baseline after detection

**Files:**
- Modify: `backend/app/services/detection_service.py` (add call after detection)
- Test: `backend/tests/e2e/test_baseline_autogen.py`

**Step 1: Write E2E test**

Test flow:
1. Seed org + agent + policy (no baseline)
2. Ingest 20 clean events via API
3. Run detection on the last event
4. Assert agent.baseline is now populated with correct shape
5. Assert known_models contains "gpt-4o"

**Step 2: Run test — verify it fails**

**Step 3: Add baseline trigger to detection_service.py**

At the end of `run_and_persist_detections()`, after persisting detections:
```python
# Auto-generate baseline if agent doesn't have one yet
if not agent.baseline:
    from app.services.baseline_service import compute_baseline
    baseline = await compute_baseline(db, agent.id)
    if baseline:
        agent.baseline = baseline
        await db.flush()
```

**Step 4: Run test — verify it passes**

**Step 5: Run full test suite to confirm no regressions**

Run: `cd backend && uv run pytest tests/ -v`

**Step 6: Commit**

---

### Task 3: E2E test — anomaly detection works with auto-generated baseline

**Files:**
- Create: `backend/tests/e2e/test_anomaly_with_baseline.py`

**Step 1: Write test**

Test flow:
1. Seed org + agent + policy
2. Ingest 20 normal events (token_count=30, latency=120ms, model=gpt-4o)
3. Run detection on last event to trigger baseline generation
4. Verify baseline was set
5. Ingest an anomalous event (token_count=5000, latency=10000ms, unknown model)
6. Run detection
7. Assert anomaly detector triggered
8. Assert incident created with anomaly details

**Step 2: Run test — verify it passes**

**Step 3: Commit**

---

### Notes

- **Minimum events threshold:** 20 events. Below that, statistical aggregates aren't meaningful.
- **Baseline is computed once:** Only when `agent.baseline` is null. Once set, it stays until manually reset or a future "recompute" feature.
- **No new API endpoints:** Baseline is fully automatic. Agents API already returns the baseline field.
- **Performance:** Single aggregate query over agent_events filtered by agent_id. TimescaleDB handles this efficiently with the agent_id index.
