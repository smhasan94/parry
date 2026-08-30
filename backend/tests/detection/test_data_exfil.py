from app.detection.detectors.data_exfil import DataExfiltrationDetector


class TestDataExfiltrationDetector:
    def setup_method(self) -> None:
        self.detector = DataExfiltrationDetector()

    def test_clean_response_no_trigger(self) -> None:
        result = self.detector.detect({"response": "The capital of France is Paris."})
        assert not result.triggered

    def test_credit_card_triggers(self) -> None:
        result = self.detector.detect({"response": "Your card is 4532-1234-5678-9012"})
        assert result.triggered
        assert result.severity.value == "critical"

    def test_ssn_triggers(self) -> None:
        result = self.detector.detect({"response": "SSN: 123-45-6789"})
        assert result.triggered
        assert result.severity.value == "critical"

    def test_api_key_triggers(self) -> None:
        result = self.detector.detect({"response": "Use this key: sk-abc123def456ghi789jkl012"})
        assert result.triggered
        assert result.severity.value == "high"

    def test_private_key_triggers(self) -> None:
        result = self.detector.detect({"response": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."})
        assert result.triggered
        assert result.severity.value == "critical"

    def test_aws_credentials_trigger(self) -> None:
        result = self.detector.detect(
            {"response": "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}
        )
        assert result.triggered

    def test_empty_response_no_trigger(self) -> None:
        result = self.detector.detect({"response": ""})
        assert not result.triggered

    def test_none_response_no_trigger(self) -> None:
        result = self.detector.detect({"response": None})
        assert not result.triggered


class TestHyphenatedApiKeys:
    """Real keys carry hyphens inside the body.

    The pattern used to stop at the second hyphen, so ``sk-proj-…`` —
    the shape OpenAI has issued for years — leaked straight through the
    detector whose entire job is catching it.
    """

    def setup_method(self) -> None:
        from app.detection.detectors.data_exfil import DataExfiltrationDetector

        self.detector = DataExfiltrationDetector()

    def test_openai_project_key_triggers(self) -> None:
        result = self.detector.detect(
            {"response": "Here you go: sk-proj-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"}
        )
        assert result.triggered

    def test_unquoted_api_key_assignment_triggers(self) -> None:
        result = self.detector.detect({"response": "API_KEY=sk-prod-7f2caaaaaaaaaaaaaaaaaa"})
        assert result.triggered

    def test_word_ending_in_sk_does_not_trigger(self) -> None:
        result = self.detector.detect(
            {"response": "The task-management-service-endpoint handles scheduling."}
        )
        assert not result.triggered

    def test_prose_about_keys_does_not_trigger(self) -> None:
        result = self.detector.detect(
            {"response": "Rotate the key if you think it leaked; ask the platform team."}
        )
        assert not result.triggered
