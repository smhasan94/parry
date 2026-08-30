# Blocker log schema

One JSON object per line in `.agent/blockers.jsonl`. Append-only. Never edit or
reorder existing lines — the export is regenerated from this file.

## Fields

| Field | Written by | Meaning |
|---|---|---|
| `id` | script | `BLK-<epoch>-<short>`, stable across regenerations |
| `date` | script | ISO 8601 with offset, when the blocker was logged |
| `worker` | script | `$CC_WORKER`, or `manual` |
| `task` | script | Task id from `.agent/running/<worker>.task`, if any |
| `branch` | script | Branch at time of logging |
| `blocker` | you | What was blocking, in one or two sentences |
| `resolution` | you | The resolution actually decided on |
| `prev_commit` | script | `git rev-parse HEAD` **before** the resolution was implemented |
| `risk` | you | `low` \| `medium` \| `high` |
| `risk_explanation` | you | Why that level — what would have to be true for it to be wrong |

## Risk is confidence in the resolution

Not severity of the blocker. A showstopper fixed by a one-line change with a
regression test is `low`. A cosmetic issue fixed by a guess is `high`.

**`low`** — The resolution is verified by something that would fail without it.
A new or existing test covers it, or a type checker proves it, or it is a
mechanical change with no behavioural surface. If you had to reason about whether
it works, it is not low.

**`medium`** — The resolution is verified by inspection or by a manual run, but
nothing in the repo will catch a regression. Also use this when the fix is correct
but the surrounding assumption is unverified (e.g. "the upstream API always returns
UTC" — true today, unenforced).

**`high`** — The resolution rests on an assumption you could not check from inside
this session. Includes: guessing at intended behaviour, working around something
you could not reproduce, choosing between two plausible interpretations of a
requirement, or anything a human would likely want to reverse. A `high` entry is a
request for review, not a failure.

## Writing a good `risk_explanation`

State the condition under which the resolution is wrong. Not "might be wrong" —
*what* would make it wrong, and how someone would find out.

Good: `Assumes retry budget is per-request, not per-connection. If it is
per-connection, this triples upstream load under failure. Verify against the
gateway's own metrics before the next release.`

Bad: `Fairly confident but not certain.`

## Regenerating the export

```
.agent/bin/render-blockers.py            # writes .md, .csv and .xlsx into .agent/export/
.agent/bin/render-blockers.py --since 2026-08-01
.agent/bin/render-blockers.py --risk high
```
