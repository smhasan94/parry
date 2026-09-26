from app.detection.registry import DETECTOR_MAP, DETECTORS
from app.proxy.check import BLOCKING_DETECTORS


def test_adversarial_suffix_detector_is_registered_in_full_pipeline():
    assert "adversarial_suffix" in DETECTOR_MAP
    assert any(d.name == "adversarial_suffix" for d in DETECTORS)


def test_adversarial_suffix_detector_is_on_the_blocking_path():
    # Registration here does NOT give pre-call protection. The
    # detector's confidence is capped at 0.65, below its 0.7 default
    # threshold, so on this path it never triggers and never blocks —
    # jb_006 itself goes through run_blocking_check with allowed=True —
    # and run_blocking_check discards non-triggering results, so nothing
    # is logged from here either. The real protection is after the fact:
    # the async pipeline routes the ambiguous-band result to the LLM
    # fallback (see test_adversarial_suffix_pipeline.py).
    #
    # What registration buys is readiness: a threshold override below
    # the ceiling would make this path block synchronously. That is not
    # reachable today — app/api/v1/proxy.py builds the blocking-path
    # event_data without the org's detector_config, so every blocking
    # detector runs at its hardcoded default — but the detector's cost is
    # already paid and budgeted here (see test_blocking_path_latency.py).
    assert any(d.name == "adversarial_suffix" for d in BLOCKING_DETECTORS)
