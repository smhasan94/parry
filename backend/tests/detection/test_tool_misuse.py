from app.detection.detectors.tool_misuse import ToolMisuseDetector


class TestToolMisuseDetector:
    def setup_method(self) -> None:
        self.detector = ToolMisuseDetector()

    def test_no_tool_calls_no_trigger(self) -> None:
        result = self.detector.detect({"tool_calls": [], "policy": {}})
        assert not result.triggered

    def test_allowed_tool_no_trigger(self) -> None:
        result = self.detector.detect(
            {
                "tool_calls": [{"name": "search"}],
                "policy": {"allowed_tools": ["search", "calculate"]},
            }
        )
        assert not result.triggered

    def test_blocked_tool_triggers(self) -> None:
        result = self.detector.detect(
            {
                "tool_calls": [{"name": "exec_code"}],
                "policy": {"blocked_tools": ["exec_code", "shell"]},
            }
        )
        assert result.triggered
        assert result.severity.value == "high"

    def test_tool_not_in_allowlist_triggers(self) -> None:
        result = self.detector.detect(
            {
                "tool_calls": [{"name": "delete_all"}],
                "policy": {"allowed_tools": ["search", "read"]},
            }
        )
        assert result.triggered

    def test_no_policy_no_trigger(self) -> None:
        result = self.detector.detect(
            {
                "tool_calls": [{"name": "anything"}],
                "policy": {},
            }
        )
        assert not result.triggered

    def test_multiple_violations(self) -> None:
        result = self.detector.detect(
            {
                "tool_calls": [{"name": "shell"}, {"name": "exec_code"}],
                "policy": {"blocked_tools": ["shell", "exec_code"]},
            }
        )
        assert result.triggered
        assert result.details is not None
        assert len(result.details["violations"]) == 2
