from app.detection.registry import DETECTOR_MAP, DETECTORS
from app.proxy.check import BLOCKING_DETECTORS


def test_adversarial_suffix_detector_is_registered_in_full_pipeline():
    assert "adversarial_suffix" in DETECTOR_MAP
    assert any(d.name == "adversarial_suffix" for d in DETECTORS)


def test_adversarial_suffix_detector_is_on_the_blocking_path():
    # The synchronous proxy path must see this attack class too — a
    # detector present only in the async registry leaves the low-
    # latency hot path blind to it (Review Focus item 5).
    assert any(d.name == "adversarial_suffix" for d in BLOCKING_DETECTORS)
