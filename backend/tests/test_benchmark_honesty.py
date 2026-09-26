"""Guards against the public benchmark drifting easier than reality.

The repo carries two corpora on purpose: the red-team corpus is
server-side, and the public benchmark endpoint is unauthenticated and
publishes a per-entry PASS/MISS badge, so it cannot serve the red-team
material without handing attackers a list of what evades Parry.

The price of that separation is drift, and it has already happened once:
the public corpus scored 93% while the red-team corpus scored 29%,
because public entries had been written using the exact wording the
patterns already matched. These tests make that failure loud.
"""

import pytest

from app.detection.red_team_corpus import load_corpus
from app.services.benchmark_service import (
    BENCHMARK_CORPUS,
    _run_detectors,
    run_benchmark,
)

# One differing entry in a six-entry category is ~17 points, which is
# ordinary corpus variation. Two is a pattern, and that is the signal.
MAX_OVERSTATEMENT_POINTS = 20

# Excluded from the public benchmark: its detectors need runtime state
# (baseline, session history, token counts) a static entry cannot carry.
EXCLUDED = {"cost_exploit"}


# `jailbreak` is expected to stay below 100% here even after the
# AdversarialSuffixDetector ships (see
# docs/superpowers/plans/2026-09-25-jailbreak-perplexity-detector.md,
# finding 6). That detector deliberately lands jb_006 in the pipeline's
# ambiguous-confidence band rather than self-triggering, because a
# confident verdict on symbol-density + case-flips alone false-positives
# on real developer bug reports (a Windows path plus a camelCase
# function name in one sentence). This function calls
# benchmark_service._run_detectors, which runs only the synchronous
# detector list — it never reaches pipeline.py's ambiguous-band
# escalation to the LLM fallback, so it structurally cannot observe
# that resolution. Task 6 in the same plan is the test that actually
# proves jb_006 resolves end-to-end. Do not "fix" this by raising this
# detector's confidence into a self-triggering range — that reintroduces
# the false positive this design avoided.
def _red_team_scores() -> dict[str, float]:
    totals: dict[str, list[int]] = {}
    for attack in load_corpus():
        if attack["category"] in EXCLUDED:
            continue
        fired = {
            r["detector"]
            for r in _run_detectors(
                attack.get("prompt") or "",
                attack.get("response"),
                attack.get("tool_calls"),
                attack.get("policy"),
            )
            if r["triggered"]
        }
        bucket = totals.setdefault(attack["category"], [0, 0])
        bucket[1] += 1
        if set(attack["expected_detectors"]) & fired:
            bucket[0] += 1
    return {cat: hit / total * 100 for cat, (hit, total) in totals.items()}


@pytest.mark.parametrize("category", sorted(_red_team_scores()))
def test_public_category_does_not_overstate_red_team(category):
    public = run_benchmark()["categories"].get(category)
    assert public is not None, f"{category} missing from the public benchmark"

    red = _red_team_scores()[category]
    overstatement = public["score"] - red
    assert overstatement <= MAX_OVERSTATEMENT_POINTS, (
        f"public benchmark reports {public['score']}% for {category} "
        f"but the red-team corpus scores {red:.0f}% — the public entries "
        f"have drifted easier than real attacks"
    )


def test_indirect_entries_are_actually_indirect():
    """An indirect entry must need the indirect detector, not just any.

    Embedding "ignore all previous instructions" inside a document fence
    produces a direct injection in costume: it scores via
    prompt_injection while testing nothing about content-borne attacks.
    """
    costumed = []
    for entry in BENCHMARK_CORPUS:
        if entry["category"] != "indirect":
            continue
        fired = {
            r["detector"]
            for r in _run_detectors(entry["prompt"], entry.get("response"), entry.get("tool_calls"))
            if r["triggered"]
        }
        if "indirect_injection" not in fired:
            costumed.append(entry["id"])
    assert not costumed, (
        f"indirect entries not detected as indirect injection: {costumed}"
    )


def test_public_overall_does_not_overstate_red_team():
    red = _red_team_scores()
    overall_red = sum(red.values()) / len(red)
    public = run_benchmark()
    attack_cats = [v for k, v in public["categories"].items() if k != "clean"]
    overall_public = sum(c["score"] for c in attack_cats) / len(attack_cats)
    assert overall_public - overall_red <= MAX_OVERSTATEMENT_POINTS
