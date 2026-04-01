from parry.interceptor import TimingContext, strip_pii


class TestStripPII:
    def test_strips_credit_card(self) -> None:
        text = "Card: 4532-1234-5678-9012"
        assert "[CREDIT_CARD]" in strip_pii(text)  # type: ignore[operator]

    def test_strips_ssn(self) -> None:
        text = "SSN is 123-45-6789"
        assert "[SSN]" in strip_pii(text)  # type: ignore[operator]

    def test_strips_email(self) -> None:
        text = "Contact me at user@example.com"
        assert "[EMAIL]" in strip_pii(text)  # type: ignore[operator]

    def test_none_returns_none(self) -> None:
        assert strip_pii(None) is None

    def test_clean_text_unchanged(self) -> None:
        text = "Hello world"
        assert strip_pii(text) == "Hello world"

    def test_multiple_pii_types(self) -> None:
        text = "Card: 4532 1234 5678 9012, email: test@test.com, SSN: 123-45-6789"
        result = strip_pii(text)
        assert result is not None
        assert "[CREDIT_CARD]" in result
        assert "[EMAIL]" in result
        assert "[SSN]" in result


class TestTimingContext:
    def test_measures_latency(self) -> None:
        with TimingContext() as t:
            _ = sum(range(1000))
        assert t.latency_ms >= 0
