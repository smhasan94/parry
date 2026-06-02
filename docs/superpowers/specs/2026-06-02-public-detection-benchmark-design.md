# Public Detection Benchmark — Design Spec

**Date:** 2026-06-02
**Status:** Approved, ready for implementation
**Purpose:** A, B, and C off one harness — marketing asset, live quality signal, CI regression gate

---

## Problem

Parry has no public, reproducible proof of its detection quality. Prospects ask "how good is it?" and get a verbal answer. The benchmark corpus already exists (`benchmark_service.py`) but is small (30 entries), disconnected from CI, and has no public surface.

---

## Goals

| Goal | What it means |
|------|---------------|
| **CI gate (C)** | PRs that regress detection quality fail automatically |
| **Live quality signal (B)** | Every push to `main` appends a score entry to a versioned JSON file; history is publicly inspectable |
| **Marketing asset (A)** | A public `/benchmark` page in the dashboard shows current score, per-category breakdown, and trend line — no login required |

---

## Non-goals

- External corpus integration (AgentDojo, OWASP) — hand-curated corpus is sufficient for v1
- LLM-based scoring — benchmark runs rule-based detectors only; LLM fallback excluded for determinism and cost
- Competitor comparison — no "vs. other tools" columns in v1

---

## Architecture

One harness (`benchmark_service.run_benchmark()`), three thin consumers:

```
benchmark_service.run_benchmark()
        │
        ├── test_benchmark_ci.py     → CI gate (pytest, every PR)
        ├── scripts/publish_benchmark.py → JSON append (CI, main only)
        └── BenchmarkPage.tsx        → public page (reads scores.json)
```

---

## 1. Corpus

**Location:** `backend/app/services/benchmark_service.py` — Python constant `BENCHMARK_CORPUS`.

**Source:** Replace the current 30 hand-crafted entries with entries derived from the existing red-team corpus (`red_team_service.py`). The red-team corpus has 48 labeled attacks across 8 categories. Each entry is wrapped to conform to the benchmark schema:

```python
{
    "id": str,           # e.g. "pi-01"
    "category": str,     # one of the 8 categories below
    "prompt": str,
    "response": str | None,  # for response-scan detectors (data_exfil)
    "expected_detectors": list[str],  # detector names that should fire
}
```

**Categories (8 attack + 1 clean) — names taken directly from corpus JSON files:**

| Category | Corpus file | Expected detector(s) |
|----------|-------------|---------------------|
| `instruction_override` | `instruction_override.json` | `prompt_injection` |
| `jailbreak` | `jailbreak.json` | `jailbreak` |
| `privilege_escalation` | `privilege_escalation.json` | `privilege_escalation` |
| `data_exfil` | `data_exfil.json` | `data_exfiltration` |
| `tool_hijack` | `tool_hijack.json` | `tool_misuse` |
| `indirect` | `indirect.json` | `prompt_injection` |
| `content_smuggling` | `content_smuggling.json` | `mcp_manifest` |
| `cost_exploit` | `cost_exploit.json` | `data_exfiltration` |
| `clean` | (hand-crafted, 10 entries) | `[]` (nothing should fire) |

**Target corpus size:** ~58 entries (48 attacks + 10 clean).

**Scoring logic (unchanged):**
- Attack entry: hit if any `expected_detectors` fires
- Clean entry: hit if nothing fires (false-positive rate)
- Per-category score = `detected / total * 100` (rounded integer)
- Overall score = `total_correct / total_entries * 100` (rounded integer)

---

## 2. CI Gate

**File:** `backend/tests/test_benchmark_ci.py`

Two assertions:

```python
def test_benchmark_overall_score_meets_threshold():
    result = run_benchmark()
    assert result["overall_score"] >= 80, (
        f"Detection benchmark dropped below threshold: {result['overall_score']}% "
        f"(required ≥ 80%). Per-category: {result['categories']}"
    )

def test_benchmark_no_category_below_floor():
    result = run_benchmark()
    for cat, data in result["categories"].items():
        if cat == "clean":
            continue  # false-positive rate tracked separately, not a merge blocker
        assert data["score"] >= 60, (
            f"Category '{cat}' dropped below floor: {data['score']}% (required ≥ 60%)"
        )
```

**Thresholds:**
- Overall: **≥ 80%** — fail the PR
- Per non-clean category: **≥ 60%** — catches a single detector silently regressing

**CI integration:** runs inside the existing `pytest` job in `.github/workflows/ci.yml`. No new job, no new infra.

---

## 3. Score Publisher

**File:** `scripts/publish_benchmark.py` (repo root `scripts/` directory)

Standalone script — no FastAPI, no DB dependency. Imports `run_benchmark` from the backend package.

**CLI:**
```
python scripts/publish_benchmark.py --version <tag_or_sha>
```

**Score entry schema:**
```json
{
  "version": "v1.2.3",
  "sha": "abc1234",
  "date": "2026-06-02T03:00:00Z",
  "overall_score": 91,
  "categories": {
    "prompt_injection": {"score": 100, "detected": 5, "total": 5},
    "jailbreak":        {"score": 80,  "detected": 4, "total": 5}
  }
}
```

**Storage:** `benchmark/scores.json` at repo root. The script reads the file (creates `[]` if missing), appends the new entry, trims to the **last 50 entries**, writes back.

**CI step** in `.github/workflows/ci.yml` — runs only on `push` to `main`, after the test job passes:

```yaml
benchmark-publish:
  needs: [test]
  runs-on: ubuntu-latest
  if: github.ref == 'refs/heads/main'
  steps:
    - uses: actions/checkout@v4
      with:
        token: ${{ secrets.GITHUB_TOKEN }}
    - uses: astral-sh/setup-uv@v4
    - name: Run and publish benchmark
      run: |
        cd backend && uv sync --frozen
        uv run python ../scripts/publish_benchmark.py --version ${{ github.sha }}
    - name: Commit scores
      run: |
        git config user.name "github-actions[bot]"
        git config user.email "github-actions[bot]@users.noreply.github.com"
        git add benchmark/scores.json
        git diff --staged --quiet || git commit -m "chore(benchmark): update scores [skip ci]"
        git push
```

The `[skip ci]` tag in the commit message prevents the score-update commit from re-triggering CI.

---

## 4. Public Page

**Route:** `/benchmark` — added to the router **before** the auth-gated layout wrapper. No Clerk auth check.

**File:** `dashboard/src/pages/BenchmarkPage.tsx`

**Data source:** `fetch('/benchmark/scores.json')` — the file is copied into Vite's `public/benchmark/` directory (or symlinked) so it's served as a static asset. No backend API call at runtime. Page works even when backend is down.

**Layout — three panels:**

**Panel 1 — Current score header**
- Large overall score number (e.g. "91")
- Letter grade: A (≥90), B (≥80), C (≥70), D (≥60), F (<60)
- Color: green ≥90, yellow ≥75, red <75
- Version tag and date of last run

**Panel 2 — Per-category breakdown**
- Horizontal bar chart, one bar per category
- Each bar: percentage + `detected/total` label
- Recharts `BarChart` — consistent with existing chart components

**Panel 3 — Score trend**
- Line chart of `overall_score` over the last 20 runs
- X axis: version/date, Y axis: 0–100
- Makes the "live quality signal" visible at a glance

**Footer:**
- Links to `docs/mcp-security.md` and `docs/red-team.md` for methodology
- Copy: "Scores computed against Parry's published attack corpus. Re-run automatically on every push to main."

---

## File Inventory

| File | Action |
|------|--------|
| `backend/app/services/benchmark_service.py` | Modify — replace corpus with red-team entries, keep scoring logic |
| `backend/tests/test_benchmark_ci.py` | Create — CI gate thresholds |
| `scripts/publish_benchmark.py` | Create — score appender |
| `benchmark/scores.json` | Create — empty array `[]` to start |
| `.github/workflows/ci.yml` | Modify — add `benchmark-publish` job |
| `dashboard/src/pages/BenchmarkPage.tsx` | Create — public page |
| `dashboard/src/routes/router.tsx` | Modify — add `/benchmark` route before auth gate |
| `dashboard/vite.config.ts` or `public/` | Modify — expose `benchmark/scores.json` as static asset |

---

## Thresholds (summary)

| Check | Threshold | Action on failure |
|-------|-----------|-------------------|
| Overall score | ≥ 80% | Block merge |
| Per category (non-clean) | ≥ 60% | Block merge |
| Clean (false-positive rate) | tracked only | No merge block |

---

## Open Questions (resolved)

- Corpus source: red-team corpus ✓
- Score storage: `benchmark/scores.json` in repo ✓
- Public page location: dashboard `/benchmark` route ✓
- Purpose: all three (A + B + C) off one harness ✓
