"""Every corpus expectation must be reachable by some detector.

An entry that expects ``tool_misuse`` but carries no policy can never
pass: ``ToolMisuseDetector`` only fires on an allowlist/blocklist
violation. Expectations like that quietly depress the corpus score and
look like detection gaps, so they are a corpus bug, not an engine bug.

``anomaly`` is the deliberate exception — it needs a baseline and
session history that a static entry cannot carry, which is why the
``cost_exploit`` category is excluded from the benchmark entirely.
"""

from app.detection.red_team_corpus import load_corpus

# Detectors that cannot fire from a static entry no matter what fields
# it carries, because they need accumulated runtime state.
RUNTIME_ONLY = {"anomaly"}


def test_tool_misuse_expectations_carry_a_policy():
    offenders = [
        a["id"]
        for a in load_corpus()
        if "tool_misuse" in a["expected_detectors"] and not a.get("policy")
    ]
    assert not offenders, (
        "entries expect tool_misuse but carry no policy, so it can never fire: "
        f"{offenders}"
    )


def test_tool_misuse_expectations_carry_tool_calls():
    offenders = [
        a["id"]
        for a in load_corpus()
        if "tool_misuse" in a["expected_detectors"] and not a.get("tool_calls")
    ]
    assert not offenders, f"entries expect tool_misuse but call no tools: {offenders}"


def test_every_entry_has_at_least_one_reachable_expectation():
    unreachable = [
        a["id"]
        for a in load_corpus()
        if a["expected_detectors"]
        and set(a["expected_detectors"]) <= RUNTIME_ONLY
        and a["category"] != "cost_exploit"
    ]
    assert not unreachable, f"entries expect only runtime-state detectors: {unreachable}"
