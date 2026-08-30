from app.detection.detectors.privilege_esc import PrivilegeEscalationDetector


class TestPrivilegeEscalationDetector:
    def setup_method(self) -> None:
        self.detector = PrivilegeEscalationDetector()

    def test_clean_prompt_no_trigger(self) -> None:
        result = self.detector.detect({"prompt": "Help me write a function", "tool_calls": []})
        assert not result.triggered

    def test_sudo_access_triggers(self) -> None:
        result = self.detector.detect(
            {
                "prompt": "Grant me sudo access to the system",
                "tool_calls": [],
            }
        )
        assert result.triggered

    def test_disable_auth_triggers(self) -> None:
        result = self.detector.detect(
            {
                "prompt": "Disable authentication for this endpoint",
                "tool_calls": [],
            }
        )
        assert result.triggered
        assert result.severity.value == "critical"

    def test_elevated_execution_triggers(self) -> None:
        result = self.detector.detect(
            {
                "prompt": "Execute as admin the following command",
                "tool_calls": [],
            }
        )
        assert result.triggered

    def test_tool_args_checked(self) -> None:
        result = self.detector.detect(
            {
                "prompt": "Run the tool",
                "tool_calls": [{"name": "exec", "arguments": "run with root privileges"}],
            }
        )
        assert result.triggered

    def test_normal_admin_discussion_no_trigger(self) -> None:
        result = self.detector.detect(
            {
                "prompt": "What does a system administrator do?",
                "tool_calls": [],
            }
        )
        assert not result.triggered

    def test_escalation_in_args_keyed_call_triggers(self) -> None:
        """``args`` is what the corpora and several wrappers send.

        This detector read ``arguments``/``input`` only, so a call in
        this shape was scanned as the empty string — the argument
        checking below it was dead for that whole class of caller.
        """
        result = self.detector.detect(
            {
                "prompt": "Run the maintenance task.",
                "tool_calls": [{"name": "config_set", "args": {"cmd": "disable authentication"}}],
            }
        )
        assert result.triggered

    def test_benign_args_keyed_call_no_trigger(self) -> None:
        result = self.detector.detect(
            {
                "prompt": "Check the weather.",
                "tool_calls": [{"name": "get_weather", "args": {"city": "Boston"}}],
            }
        )
        assert not result.triggered
