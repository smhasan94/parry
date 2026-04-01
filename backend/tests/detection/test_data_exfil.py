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
        result = self.detector.detect(
            {"response": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."}
        )
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
