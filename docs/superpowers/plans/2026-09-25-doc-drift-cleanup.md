# Doc-Drift Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 5 still-open documentation/docstring discrepancies listed in `docs/codebase-breakdown.md` §8 (items 2, 3, 4, 6, 7 — items 1 and 5 are already marked RESOLVED), so the repo's docs match its code.

**Architecture:** This is a documentation-accuracy pass, not a feature. Every task is "read the current code, correct the doc/docstring that disagrees with it, commit." No task changes runtime behavior, so none needs a test step — except there is no such task here; verification below confirmed the cheaper fix (correct the doc) is right in every case, including item 2 where a bigger fix (persisting the hash chain in the DB) was considered and rejected.

**Tech Stack:** Markdown files, one Python docstring. No build step, no test runner beyond a final read-through diff.

**Spec:** `docs/codebase-breakdown.md` §8 (the discrepancy table this plan closes out) — read it alongside this plan; each task below cites the exact table row it resolves.

## Global Constraints

- Commit messages use `docs:` type per repo convention (`git-workflow.md`) — one commit per task, no bundling.
- Don't touch items 1 and 5 in the table — already RESOLVED.
- Don't invent numbers. Every count in this plan was produced by a command, not estimated; if you change a task's file between planning and execution, re-run the same command before writing a new number.
- Preserve existing table/doc formatting conventions in each file (Markdown table pipes, docstring indentation) — no reformatting beyond the cells that are actually wrong.
- Task 6 (updating `docs/codebase-breakdown.md` itself) must run last, after 2–5 are committed, so its "RESOLVED" annotations describe fixes that actually landed.

## Review Focus

- **Numbers drift again immediately.** Backend test count was 1,148 when the table was written, is 1,298 now, and will be higher again next week. Task 3 phrases the fix so it doesn't need re-verifying every time someone adds a test file (see Task 3 for the exact wording chosen).
- **The same stale claim appears in more than one place.** The audit-log wording (item 2) and the adr reference (item 6) were checked repo-wide, not just at the file:line the table cites — Task 1 and Task 4 each fix every occurrence found, not just the first.
- **A "fix the doc" item might actually mean "fix the code."** Item 2 was evaluated both ways: is the missing `prev_hash` column a real gap worth closing, or is the docstring's stated reasoning ("not tamper-proof at the DB layer... goal is a self-contained artefact") the right design? Task 1 documents which was chosen and why, rather than silently picking one.
- **A table row's own cited evidence might have moved.** Every file:line in the source table (audit_export_service.py:14, models.py:245-246/351-376, pipeline.py's docstring) was re-read against the current tree before writing tasks — none had moved, but a future editor re-running this plan after further drift should re-check, not trust the plan's line numbers blindly.
- **Fixing the symptom without closing the loop.** If `docs/codebase-breakdown.md` §8 isn't updated to RESOLVED after 2–5 land, the same 5 items will resurface as "still open" in the next status read. Task 6 exists specifically to prevent that.

---

## Problem Statement — verified current state

Re-checked against the tree at `main` (HEAD `59e437f`, 2026-09-25) before writing tasks. All 5 items are still live; none had drifted further since the table was written.

**Item 2 — README: "tamper-evident hash-chained audit log."**
Confirmed still true: `backend/app/services/audit_export_service.py`'s module docstring states explicitly the chain is **per-export**, computed as `row_hash_n = sha256(prev_hash_{n-1} + canonical_json(row_n))`, and gives the reason: the `audit_log` table (`backend/app/db/models.py:351-376`) is "append-only from application code (not tamper-proof at the DB layer)," so the goal is a self-contained artefact an auditor can verify offline, not a persisted chain. **Decision: fix the words, not the code.** Persisting a `prev_hash` column wouldn't add real tamper-evidence beyond what the per-export chain already gives (a row could still be edited between exports at the DB layer regardless of a stored column), so it would be cosmetic complexity for a claim the docstring already argues against. Also found the same overclaim repeated at `README.md:144` (feature list) — the table only cited the general claim, not the specific line, so Task 1 fixes both `README.md:144` and confirms no other file overclaims it (`docs/schema.md:163` says "Append-only tamper-evident record," which is accurate and untouched).

**Item 3 — docs/architecture.md `agent_events` schema table.**
Confirmed still stale at `docs/architecture.md` lines 81-91: it lists `prompt_hash`, `prompt_preview`, `response_preview` columns. The actual model (`backend/app/db/models.py:245-246`) has `prompt: Mapped[str | None] = mapped_column(Text, nullable=True)` and `response: Mapped[str | None] = mapped_column(Text, nullable=True)` — full text, no hash, no preview truncation, no DB-side PII stripping. Fix: replace those 3 rows with the real columns.

**Item 4 — README test counts.**
Confirmed stale, and stale in a new place too: the table's own "~1,350+" figure is now itself outdated (things kept moving since the table was written). Fresh counts as of this tree:
- Backend: `grep -rc "def test_" backend --include="*.py"` → **1,298**
- Python SDK: `grep -rc "def test_" sdk --include="*.py"` → **139**
- TypeScript SDK: `grep -rc "it(\|test(" sdk-ts/tests sdk-ts/test sdk-ts/src` → **92**
- Go SDK: `grep -rc "^func Test" sdk-go --include="*.go"` → **16**
- Dashboard: `find dashboard -name "*.test.*"` → **32 test files** (Vitest — file count, not function count, since dashboard tests aren't one-`test_`-per-function the way the others are)

README currently claims, and Task 3 fixes: `README.md:144` "700+ tests" (feature list is actually a different line — see Task 3), `README.md:248` "700+ tests", `README.md:301` "Backend (600+ unit tests)", `README.md:304` "Python SDK (90 tests)", `README.md:307` "TypeScript SDK (19 tests)" — this one is off by nearly 5x, the worst of the five, `README.md:310` "Go SDK (14 tests)".

**Item 6 — CLAUDE.md `docs/adr/` reference.**
Confirmed `docs/adr/` does not exist (`ls docs/adr` → no such file or directory). `CLAUDE.md` references it twice: line 40 (repo-layout tree comment `# Architecture, ADRs, API specs`) and line 170 (prose: "ADRs (Architecture Decision Records): `docs/adr/`"). Both need fixing, not just one. Also found, while checking: `docs/plans/plan-13-17-next-wave.md:615` instructs a worker to "Write `docs/adr/013-mcp-security-scope.md`" documenting the MCP security scope decision — that ADR was apparently never written (the directory doesn't exist at all), and the MCP SSRF work that plan was part of has since shipped. That's a real gap, but it's a scope decision (write a retroactive ADR, or create the directory now) beyond "fix the doc to match the code" — flagging it here rather than folding it into this task; see note after Task 4.

**Item 7 — `DetectionPipeline` docstring.**
Confirmed still stale at `backend/app/detection/pipeline.py:17-25`. Docstring lists 4 stages including "3. Check policy enforcement." `run()` (lines 27+) only does: filter enabled detectors, normalize prompt once, fan out detectors via thread pool, gather results. There's no separate policy-enforcement stage in this method — policy is merged upstream and consumed inside individual detectors (tool-misuse/policy-logic), not as a pipeline stage. Fix: correct the docstring to describe the 3 real stages.

---

### Task 1: Fix the audit-log overclaim (item 2)

**Files:**
- Modify: `README.md:144`

**Interfaces:** None — text-only change, no code interfaces involved.

- [ ] **Step 1: Edit the feature-list line**

In `README.md`, line 144 currently reads:

```
- **Audit**: Tamper-evident hash-chained audit log with SOC 2 export
```

Change to:

```
- **Audit**: Verifiable hash-chained audit export (per-export chain, SOC 2 style) with tamper-evident append-only storage
```

This keeps both true claims — the table's own append-only model docstring ("Tamper-evident record of who did what," `backend/app/db/models.py:352`) and the per-export verifiable chain — without implying the chain itself is persisted.

- [ ] **Step 2: Confirm no other file repeats the overclaim**

Run: `grep -rn "hash-chained\|tamper-evident" --include="*.md" .`
Expected: only `README.md:144` (now fixed), `docs/schema.md:163` ("Append-only tamper-evident record" — accurate, leave as-is), `docs/codebase-breakdown.md:209` (the table row itself — Task 6 handles this), and `docs/plans/plan-13-17-next-wave.md:3613` (a comment in a completed plan's file listing — historical, leave as-is).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: stop overclaiming a persisted hash chain in the audit log

The chain is computed per-export by design (audit_export_service.py's
own docstring explains why: the table isn't tamper-proof at the DB
layer, so the goal is a self-contained offline-verifiable artefact,
not a stored chain). Phrase the feature list to match."
```

---

### Task 2: Fix the `agent_events` schema table (item 3)

**Files:**
- Modify: `docs/architecture.md:87-89`

**Interfaces:** None — text-only change.

- [ ] **Step 1: Replace the stale rows**

In `docs/architecture.md`, the `agent_events` table currently has (lines 87-89):

```
| prompt_hash | text | SHA-256 of original prompt |
| prompt_preview | text | first 200 chars, PII-stripped |
| response_preview | text | first 200 chars, PII-stripped |
```

Replace with:

```
| prompt | text | full prompt text; PII stripping happens client-side in the SDK before send, not in this column |
| response | text | full response text; same client-side PII note applies |
```

- [ ] **Step 2: Verify against the model**

Run: `grep -n "prompt:\|response:" backend/app/db/models.py`
Expected: shows `prompt: Mapped[str | None] = mapped_column(Text, nullable=True)` and `response: Mapped[str | None] = mapped_column(Text, nullable=True)` at lines 245-246, confirming the doc now matches.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: correct agent_events schema — full prompt/response, not hashed previews

The model stores full Text columns; there's no DB-side hashing or
truncation. PII stripping is client-side in the SDK only."
```

---

### Task 3: Fix stale test counts (item 4)

**Files:**
- Modify: `README.md:248, 301, 304, 307, 310`

**Interfaces:** None — text-only change.

- [ ] **Step 1: Fix the tech-stack table row**

`README.md:248` currently:

```
| **Testing** | 700+ tests (backend unit + E2E, Python SDK, TypeScript SDK, Go, dashboard) |
```

Change to:

```
| **Testing** | 1,500+ tests (backend unit + E2E, Python SDK, TypeScript SDK, Go, dashboard) — see `docs/codebase-breakdown.md` §4 for a per-suite breakdown, since per-suite numbers here go stale faster than this line |
```

Using a round "1,500+" (current total across the 5 suites is 1,298 + 139 + 92 + 16 = 1,545, plus 32 dashboard test files not counted the same way) rather than an exact figure, and pointing at the breakdown doc for the real per-suite counts, is the deliberate fix for the Review Focus item about numbers drifting again — this line won't need editing again for a while, and the one doc that does need editing (`codebase-breakdown.md`) is the one this plan's Task 6 already re-verifies.

- [ ] **Step 2: Fix the per-suite counts in "Running Tests"**

`README.md:301,304,307,310` currently:

```
# Backend (600+ unit tests)
...
# Python SDK (90 tests)
...
# TypeScript SDK (19 tests)
...
# Go SDK (14 tests)
```

Change to:

```
# Backend (1,298 unit tests)
...
# Python SDK (139 tests)
...
# TypeScript SDK (92 tests)
...
# Go SDK (16 tests)
```

These are exact counts from the commands in the Problem Statement above (not "+"), because this section is explicitly instructional ("run these commands to test each suite") rather than a marketing-style feature list — precision is more useful to a reader here than a round number.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update test counts — grown from 700+/600+/90/19/14 to current figures

Backend def test_ count is 1,298 (was 1,148 when last measured), Python
SDK 139, TypeScript SDK 92 (was 19 — the worst of the stale figures),
Go SDK 16. Top-line figure now says '1,500+' and points at
codebase-breakdown.md's per-suite table instead of hardcoding numbers
that need re-verifying every time a test file is added."
```

---

### Task 4: Fix the `docs/adr/` reference (item 6)

**Files:**
- Modify: `CLAUDE.md:40, 170`

**Interfaces:** None — text-only change.

- [ ] **Step 1: Fix the repo-layout tree comment**

`CLAUDE.md:40` currently:

```
├── docs/             # Architecture, ADRs, API specs
```

Change to:

```
├── docs/             # Architecture, plans, API specs
```

- [ ] **Step 2: Fix the prose reference**

`CLAUDE.md:170` currently:

```
- ADRs (Architecture Decision Records): `docs/adr/`
```

Change to:

```
- Architecture rationale: module docstrings (inline, next to the code they explain) and `docs/plans/` (design decisions made when a feature was planned). No `docs/adr/` directory — this repo doesn't keep separate ADRs.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: stop referencing a docs/adr/ directory that doesn't exist

Rationale lives in module docstrings and docs/plans/ instead. Fixes
both mentions (repo-layout tree comment and the prose reference list)."
```

**Note — not a task in this plan, flagging for a separate decision:** `docs/plans/plan-13-17-next-wave.md:615` instructed a worker to write `docs/adr/013-mcp-security-scope.md` documenting the MCP security scope decision; that never happened, and the MCP SSRF hardening work from that same plan has since shipped on main. Whether to (a) write that ADR retroactively and start a real `docs/adr/` directory, or (b) leave it as dropped scope now that CLAUDE.md no longer promises the directory exists, is a product decision about documentation practice, not a drift-fix — raise it separately rather than deciding it inside this cleanup.

---

### Task 5: Fix the `DetectionPipeline` docstring (item 7)

**Files:**
- Modify: `backend/app/detection/pipeline.py:17-25`

**Interfaces:** None — docstring-only change; `run()`'s signature and behavior are untouched.

- [ ] **Step 1: Edit the docstring**

`backend/app/detection/pipeline.py:17-25` currently:

```python
class DetectionPipeline:
    """Orchestrates the full detection pipeline for an event.

    Pipeline stages:
    1. Run all rule-based detectors in parallel
    2. Aggregate scores — if ambiguous (0.4–0.7), flag for LLM fallback
    3. Check policy enforcement
    4. Return all results
    """
```

Change to:

```python
class DetectionPipeline:
    """Orchestrates the full detection pipeline for an event.

    Pipeline stages:
    1. Filter to enabled detectors and normalize the prompt once
       (shared across the thread-pool fan-out, not recomputed per detector)
    2. Run all rule-based detectors in parallel via a thread pool
    3. Aggregate scores — if ambiguous (0.4–0.7), flag for LLM fallback

    There is no separate policy-enforcement stage here: policy is merged
    upstream and consumed inside individual detectors (tool-misuse,
    policy-logic), not as a pipeline step.
    """
```

- [ ] **Step 2: Verify against `run()`**

Run: `sed -n '17,45p' backend/app/detection/pipeline.py`
Expected: the docstring's 3 stages now match what `run()` actually does (filter+normalize, thread-pool fan-out, gather — LLM fallback dispatch happens in the caller per the existing table's item 3.1 discussion, not inside this method; confirm that's still true by checking `run()` doesn't call an LLM fallback function directly).

- [ ] **Step 3: Commit**

```bash
git add backend/app/detection/pipeline.py
git commit -m "docs: fix DetectionPipeline docstring — no separate policy stage

Policy is consumed inside individual detectors, not as a distinct
pipeline stage. Docstring now lists the 3 stages run() actually
performs."
```

---

### Task 6: Mark items 2, 3, 4, 6, 7 RESOLVED in the source table

**Files:**
- Modify: `docs/codebase-breakdown.md:209,210,211,213,214`

**Interfaces:** Consumes: the commit hashes from Tasks 1-5 (run `git log --oneline -5` after Task 5's commit to get them).

- [ ] **Step 1: Re-verify each fix landed**

Run: `grep -n "Verifiable hash-chained\|prompt.*full prompt text\|1,298 unit tests\|Architecture rationale: module docstrings\|no separate policy-enforcement stage" README.md docs/architecture.md CLAUDE.md backend/app/detection/pipeline.py`
Expected: one match per file, confirming Tasks 1-5 landed before this table is annotated as resolved.

- [ ] **Step 2: Edit each row to match the RESOLVED style already used for items 1 and 5**

For each of rows 2, 3, 4, 6, 7 in `docs/codebase-breakdown.md` §8, prefix the "Claim" cell with a strikethrough and a **RESOLVED** note, following the exact pattern items 1 and 5 already use, e.g. row 2 becomes:

```
| 2 | ~~README: "tamper-evident hash-chained audit log."~~ **RESOLVED** — now reads "Verifiable hash-chained audit export (per-export chain, SOC 2 style) with tamper-evident append-only storage." | The chain is computed **per-export**, not persisted. `audit_export_service.py:14` says so explicitly; the `audit_log` table has no `prev_hash` column (`models.py:351–376`). It's append-only-by-convention with a verifiable export. This was a wording fix, not a code fix — see the plan's Problem Statement for why persisting the chain wasn't worth doing. |
```

Apply the same pattern to rows 3, 4, 6, 7, each referencing what it was changed to (row 4 should also note the new "point at codebase-breakdown.md §4 instead of a hardcoded number" approach, since that's the mechanism preventing this row from going stale again).

- [ ] **Step 3: Commit**

```bash
git add docs/codebase-breakdown.md
git commit -m "docs: mark discrepancy items 2, 3, 4, 6, 7 RESOLVED

All 7 items in §8 are now closed. See docs/superpowers/plans/2026-09-25-doc-drift-cleanup.md for the fixes."
```

---

## No Placeholders check (self-review)

Every step above shows the literal before/after text, not a description of what to change — verified by re-reading each task. No "TBD," no "add appropriate," no "similar to Task N."

## Spec coverage check (self-review)

Table rows 2, 3, 4, 6, 7 each map to exactly one task (1, 2, 3, 4, 5) plus the closing Task 6. Rows 1 and 5 are untouched, as instructed. No row is missing a task.

## Type/reference consistency check (self-review)

Line numbers cited (README.md:144/248/301/304/307/310, docs/architecture.md:87-89, CLAUDE.md:40/170, pipeline.py:17-25) were all re-read from the live tree during Problem Statement verification, not copied from the source table blind. Task 6 explicitly re-verifies all five before annotating RESOLVED, so a line-number drift between planning and execution gets caught rather than silently mis-annotated.
