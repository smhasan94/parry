"""Make obfuscated prompts legible to the pattern-based detectors.

Attackers hide a payload from a literal regex while leaving it perfectly
readable to the model: a zero-width space inside a keyword, a Cyrillic
``о`` standing in for ASCII ``o``, or the whole instruction wrapped in
base64. The detectors should not each have to know about encodings, so
this module collapses those tricks into one canonical text that the
ordinary patterns are run against.

Two rules keep this honest:

* **Never delete a word boundary.** NBSP becomes a space, not nothing —
  fusing two words would hide a payload rather than expose one.
* **Only append a decoded payload when it looks like language.** A hex
  digest is valid base64; blindly appending its bytes would be noise,
  and a rot13 view of every prompt would double the text scanned on the
  ``/proxy/check`` path for nothing.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import re
from typing import Any

import structlog

log = structlog.get_logger()

# Memory guard only. This used to be 200k, which silently dropped
# detection input: a payload past the cut simply was not scanned, and
# nothing said so. The synchronous path now bounds its own input before
# calling here (proxy.check.bounded_scan_source), so this cap exists for
# the Celery worker, where correctness outranks speed — normalizing 5MB
# measures in tens of milliseconds there. Truncation is logged because a
# silent one is indistinguishable from a clean scan.
MAX_INPUT = 1_000_000

# Shifting a whole prompt and scanning the result for English is the
# dominant cost of normalization on large inputs. A smuggled rot13
# payload is short, so past this size the trade stops being worth it.
MAX_ROT13_INPUT = 4_096

# Longest base64 token worth attempting. Decoding scales with length and
# a real smuggled instruction is far shorter than this.
MAX_B64_TOKEN = 8_192

# Zero-width and formatting codepoints. These carry no visual width, so
# "ig<ZWSP>nore" reads as "ignore" but matches no literal pattern.
_INVISIBLE = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD],
)

# Non-breaking space is whitespace, not decoration — map it, don't drop it.
_SPACES = {0x00A0: " ", 0x2007: " ", 0x202F: " "}

# Unicode tag block. U+E0000 + n mirrors ASCII codepoint n, which makes
# it a channel for text that is invisible in every renderer.
_TAG_BASE = 0xE0000
_TAG_LAST = 0xE007F

# Confusables NFKC does not fold, because they are distinct letters in
# their own scripts. Cyrillic first, then Greek.
_HOMOGLYPHS = {
    "а": "a",
    "в": "b",
    "е": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "ο": "o",
    "α": "a",
    "ε": "e",
    "ρ": "p",
    "ν": "v",
    "τ": "t",
    "ι": "i",
    "κ": "k",
    "μ": "m",
    "χ": "x",
    "Ο": "O",
    "Α": "A",
    "Ε": "E",
    "Ρ": "P",
    "Τ": "T",
    "Κ": "K",
    "Μ": "M",
    "Χ": "X",
}

_TRANSLATION = {
    **_INVISIBLE,
    **_SPACES,
    **{ord(k): v for k, v in _HOMOGLYPHS.items()},
    **{cp: chr(cp - _TAG_BASE) for cp in range(_TAG_BASE, _TAG_LAST + 1)},
}

_B64_TOKEN = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_WORD = re.compile(r"[a-z]{3,}")

# Enough common English to tell a decoded instruction from decoded noise.
_COMMON_WORDS = frozenset(
    [
        "above",
        "access",
        "act",
        "admin",
        "all",
        "and",
        "any",
        "are",
        "can",
        "could",
        "data",
        "delete",
        "disregard",
        "email",
        "execute",
        "file",
        "files",
        "follow",
        "for",
        "forget",
        "from",
        "give",
        "has",
        "have",
        "ignore",
        "instead",
        "instruction",
        "instructions",
        "key",
        "keys",
        "mode",
        "must",
        "not",
        "now",
        "password",
        "please",
        "previous",
        "print",
        "prior",
        "prompt",
        "prompts",
        "rather",
        "read",
        "reveal",
        "role",
        "run",
        "secret",
        "send",
        "should",
        "show",
        "system",
        "tell",
        "than",
        "that",
        "the",
        "then",
        "this",
        "token",
        "user",
        "users",
        "was",
        "were",
        "will",
        "with",
        "would",
        "write",
        "you",
        "your",
    ]
)


def _looks_like_language(text: str) -> bool:
    """True when a decoded blob reads as English rather than as bytes.

    Two hits is deliberately low: a smuggled instruction is short, and
    the cost of a false negative here is a missed attack while the cost
    of a false positive is a little extra text to scan.
    """
    words = _WORD.findall(text.lower())
    return sum(1 for w in words if w in _COMMON_WORDS) >= 2


def _decode_base64_payloads(text: str) -> list[str]:
    out: list[str] = []
    for token in _B64_TOKEN.findall(text):
        if len(token) > MAX_B64_TOKEN or len(token) % 4:
            continue
        try:
            raw = base64.b64decode(token, validate=True)
        except (binascii.Error, ValueError):
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if _looks_like_language(decoded):
            out.append(decoded)
    return out


def _decode_rot13(text: str) -> list[str]:
    if len(text) > MAX_ROT13_INPUT:
        return []
    shifted = codecs.decode(text, "rot13")
    return [shifted] if _looks_like_language(shifted) else []


def normalize(prompt: str) -> str:
    """Return the text detectors should pattern-match against.

    The cleaned original always comes first, so anything a detector
    reports still corresponds to something the reader can see. Decoded
    payloads are appended after it.
    """
    if not prompt:
        return ""

    if len(prompt) > MAX_INPUT:
        log.warning("normalize.truncated", length=len(prompt), cap=MAX_INPUT)

    cleaned = prompt[:MAX_INPUT].translate(_TRANSLATION)

    extra = _decode_base64_payloads(cleaned) + _decode_rot13(cleaned)
    if not extra:
        return cleaned
    return "\n".join([cleaned, *extra])


def scan_text(event_data: dict[str, Any]) -> str:
    """Normalized prompt for this event, computed once per event.

    ``DetectionPipeline`` fans detectors out across a thread pool over a
    single shared ``event_data``, so it precomputes ``_scan_text``
    before dispatch. The fallback keeps detectors usable standalone —
    unit tests, the benchmark harness and the tuning sandbox all build
    an ``event_data`` by hand and call ``detect`` directly.
    """
    precomputed = event_data.get("_scan_text")
    if isinstance(precomputed, str):
        return precomputed
    return normalize(event_data.get("prompt") or "")
