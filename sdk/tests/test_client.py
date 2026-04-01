from parry.client import _truncate


class TestTruncate:
    def test_truncates_long_text(self) -> None:
        text = "a" * 5000
        result = _truncate(text, 4000)
        assert result is not None
        assert len(result) == 4000

    def test_short_text_unchanged(self) -> None:
        assert _truncate("hello", 4000) == "hello"

    def test_none_returns_none(self) -> None:
        assert _truncate(None, 4000) is None

    def test_exact_length_unchanged(self) -> None:
        text = "a" * 4000
        assert _truncate(text, 4000) == text
