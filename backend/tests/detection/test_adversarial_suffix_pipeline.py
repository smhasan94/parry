"""Proves jb_006 resolves end-to-end, not just at the rule-based layer.

test_benchmark_honesty.py cannot observe this — it only runs the
synchronous detector list (see the comment added to that file in this
same change). This test runs the actual async pipeline, including the
ambiguous-confidence escalation to the LLM fallback, with the Anthropic
call mocked the same way test_llm_fallback.py does it.

Two things this file discovered that the plan's starting hypothesis
(task-6-brief.md) got wrong, both fixed here rather than papered over:

1. There is no module-level ``app.detection.pipeline.run`` function.
   The real interface is the ``DetectionPipeline`` class with an
   instance ``.run()`` coroutine method (see
   ``app.services.detection_service`` and
   ``app.workers.red_team_task`` for the two real call sites, and
   ``tests/detection/test_pipeline.py`` for the existing test
   convention this file follows).
2. ``llm_fallback.py`` does a lazy ``import anthropic`` inside
   ``evaluate_ambiguous`` and calls ``anthropic.AsyncAnthropic(...)``
   at call time — there is no ``AsyncAnthropic`` name bound in the
   ``llm_fallback`` module's own namespace to patch. The correct mock
   target is ``anthropic.AsyncAnthropic`` itself, exactly as
   ``test_llm_fallback.py`` does it.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.detection.pipeline import DetectionPipeline
from app.detection.red_team_corpus import load_corpus

# Pull the exact corpus prompt by id rather than hand-copying its
# escaped text, so this test can never silently drift from the entry
# test_benchmark_honesty.py is talking about.
JB_006_PROMPT = next(
    attack["prompt"] for attack in load_corpus() if attack["id"] == "jb_006_universal_trigger"
)


def _mock_anthropic_response(content: dict) -> MagicMock:
    block = MagicMock()
    block.text = json.dumps(content)
    msg = MagicMock()
    msg.content = [block]
    msg.usage = MagicMock(input_tokens=100, output_tokens=50)
    return msg


@pytest.mark.asyncio
async def test_jb_006_resolves_to_jailbreak_via_llm_fallback():
    event_data = {
        "prompt": JB_006_PROMPT,
        "response": "",
        "model": "gpt-4o",
        "tool_calls": [],
        "policy": {},
    }

    with patch("app.core.config.settings") as mock_settings:
        mock_settings.on_prem_mode = False
        mock_settings.anthropic_api_key = "sk-ant-test"
        with patch("anthropic.AsyncAnthropic") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.messages.create = AsyncMock(
                return_value=_mock_anthropic_response(
                    {
                        "is_threat": True,
                        "severity": "critical",
                        "confidence": 0.9,
                        "reason": "Optimizer-generated adversarial suffix requesting harmful content.",
                    }
                )
            )

            pipeline = DetectionPipeline()
            results = await pipeline.run(event_data)

    by_detector = {r.detector: r for r in results}

    # The rule-based detector must land the prompt in the ambiguous
    # band (confidence 0.4-0.7, NOT triggered) rather than self-trigger.
    # If this ever stops being true, the LLM fallback in this test
    # would never be invoked and the test would be proving nothing.
    adversarial_suffix_result = by_detector["adversarial_suffix"]
    assert adversarial_suffix_result.triggered is False
    assert 0.4 <= adversarial_suffix_result.confidence <= 0.7

    # The mocked Anthropic call must actually have been made — proves
    # the pipeline really escalated to evaluate_ambiguous rather than
    # some other detector coincidentally resolving the prompt on its own.
    mock_client.messages.create.assert_awaited_once()

    # The escalation's own verdict must be present and reflect the
    # mocked Claude response — this is the specific mechanism finding 6
    # says the benchmark-honesty test cannot observe.
    assert "llm_fallback" in by_detector
    fallback_result = by_detector["llm_fallback"]
    assert fallback_result.triggered is True
    assert fallback_result.confidence == 0.9
    assert fallback_result.details["ambiguous_detectors"] == ["adversarial_suffix"]

    # And the pipeline's own top-level verdict — the thing that
    # actually matters in production — must now say "block this call".
    assert pipeline.should_block(results) is True
