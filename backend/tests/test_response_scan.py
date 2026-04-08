"""Unit tests for the synchronous response scanner.

Targets scan_response directly — no API, no DB — so these run in
<10ms and cover the exact logic that sits in the LLM return path.
"""

import pytest

from app.db.models import ResponseScanMode
from app.proxy.response_scan import scan_response

CLEAN = "Paris is the capital of France."
SSN = "Here is your SSN: 123-45-6789"
CREDIT_CARD = "Card number 4111 1111 1111 1111 on file"
API_KEY = 'api_key: "sk-abcdefghijklmnopqrstuvwxyz1234"'


def test_off_mode_never_touches_response():
    result = scan_response(SSN, ResponseScanMode.OFF)
    assert result.blocked is False
    assert result.redacted_response == SSN
    assert result.findings == []
    assert result.original_response == SSN


def test_redact_mode_clean_response_unchanged():
    result = scan_response(CLEAN, ResponseScanMode.REDACT)
    assert result.blocked is False
    assert result.redacted_response == CLEAN
    assert result.findings == []


def test_redact_mode_ssn_replaced():
    result = scan_response(SSN, ResponseScanMode.REDACT)
    assert result.blocked is False
    assert "123-45-6789" not in result.redacted_response
    assert "[REDACTED:SSN_DETECTED]" in result.redacted_response
    assert any("SSN" in f["pattern"] for f in result.findings)
    # Original preserved on the result for forensics
    assert result.original_response == SSN


def test_redact_mode_credit_card_replaced():
    result = scan_response(CREDIT_CARD, ResponseScanMode.REDACT)
    assert result.blocked is False
    assert "4111 1111 1111 1111" not in result.redacted_response
    assert "[REDACTED:CREDIT_CARD_NUMBER_DETECTED]" in result.redacted_response


def test_redact_mode_api_key_replaced():
    result = scan_response(API_KEY, ResponseScanMode.REDACT)
    assert result.blocked is False
    assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in result.redacted_response
    assert "[REDACTED:API_KEY_OR_SECRET_DETECTED]" in result.redacted_response


def test_block_mode_sensitive_data_blocks():
    result = scan_response(SSN, ResponseScanMode.BLOCK)
    assert result.blocked is True
    assert result.redacted_response is None
    assert any("SSN" in f["pattern"] for f in result.findings)
    # Original still preserved for forensics
    assert result.original_response == SSN


def test_block_mode_clean_response_passes():
    result = scan_response(CLEAN, ResponseScanMode.BLOCK)
    assert result.blocked is False
    assert result.redacted_response == CLEAN
    assert result.findings == []


@pytest.mark.parametrize(
    "mode",
    [ResponseScanMode.OFF, ResponseScanMode.REDACT, ResponseScanMode.BLOCK],
)
def test_empty_response_never_blocks(mode):
    """Edge case: an empty string must not produce a block or crash
    on any mode. The detector is robust to empty input but we want
    an explicit guard so this stays true after future refactors."""
    result = scan_response("", mode)
    assert result.blocked is False
    assert result.redacted_response == ""
