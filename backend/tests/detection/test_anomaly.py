from app.detection.detectors.anomaly import AnomalyDetector


class TestAnomalyDetector:
    def setup_method(self) -> None:
        self.detector = AnomalyDetector()

    def test_no_baseline_no_trigger(self) -> None:
        result = self.detector.detect({"baseline": None})
        assert not result.triggered
        assert result.confidence == 0.0

    def test_within_baseline_no_trigger(self) -> None:
        result = self.detector.detect({
            "token_count": 100,
            "latency_ms": 200,
            "tool_calls": [{"name": "search"}],
            "model": "gpt-4o",
            "baseline": {
                "avg_token_count": 110,
                "std_token_count": 30,
                "avg_latency_ms": 190,
                "std_latency_ms": 50,
                "avg_tool_calls": 1.5,
                "known_models": ["gpt-4o"],
            },
        })
        assert not result.triggered

    def test_token_anomaly_triggers(self) -> None:
        result = self.detector.detect({
            "token_count": 5000,
            "latency_ms": 200,
            "tool_calls": [],
            "model": "gpt-4o",
            "baseline": {
                "avg_token_count": 100,
                "std_token_count": 20,
                "avg_latency_ms": 200,
                "std_latency_ms": 50,
                "known_models": ["gpt-4o"],
            },
        })
        assert result.triggered

    def test_unknown_model_triggers(self) -> None:
        result = self.detector.detect({
            "token_count": 100,
            "latency_ms": 200,
            "tool_calls": [],
            "model": "unknown-model-v2",
            "baseline": {
                "avg_token_count": 100,
                "std_token_count": 20,
                "avg_latency_ms": 200,
                "std_latency_ms": 50,
                "known_models": ["gpt-4o", "gpt-4o-mini"],
            },
        })
        assert result.triggered

    def test_excessive_tool_calls_triggers(self) -> None:
        result = self.detector.detect({
            "token_count": 100,
            "latency_ms": 200,
            "tool_calls": [{"name": f"tool_{i}"} for i in range(10)],
            "model": "gpt-4o",
            "baseline": {
                "avg_token_count": 100,
                "std_token_count": 20,
                "avg_latency_ms": 200,
                "std_latency_ms": 50,
                "avg_tool_calls": 2.0,
                "known_models": ["gpt-4o"],
            },
        })
        assert result.triggered
