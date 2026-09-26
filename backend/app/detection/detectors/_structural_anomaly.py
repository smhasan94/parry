"""Detects the structural fingerprint of BPE-detokenization artifacts.

GCG-style adversarial suffixes (Zou et al. 2023, arXiv:2307.15043) are
optimizer-generated token sequences, not language. Their letters still
read as mostly-ordinary English (the optimizer keeps the words that
survive the loss), so a language-model perplexity check over letters
does not separate them from clean prose — see the plan this module
implements for the measured numbers. What does not survive is
orthography: real BPE-detokenization garbage mixes symbols that almost
never appear in prose (backslash, pipe, tilde, caret — chosen narrowly;
``* [ ] ( )`` are excluded because Markdown emphasis and links use them
constantly) with mid-token case flips (``similarlyNow``) that a human
writer does not produce.

Neither signal alone is safe: symbol density alone false-positives on
Windows paths and regex; case flips alone false-positive on camelCase
identifiers mentioned in prose. Only their co-occurrence, scaled by how
much of the text either signal touches, is used here — and even then
this function must not be trusted as a confident verdict. Its caller
(``adversarial_suffix.py``) deliberately keeps this in the pipeline's
ambiguous-confidence band rather than self-triggering, because a
realistic developer bug report (a Windows path plus a camelCase
function name in the same sentence) can still score high.
"""

from __future__ import annotations

import re

_FENCED_CODE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S+")

# Deliberately excludes `* [ ] ( )` — common in Markdown emphasis and
# links, so including them reintroduced the exact false-positive class
# 6b1663e was written to remove.
_UNUSUAL_SYMBOLS = frozenset("\\|~^")

_CASE_FLIP = re.compile(r"[a-z][A-Z]")

# Below this many non-whitespace characters (after code-stripping),
# there isn't enough text for either signal to mean anything.
MIN_SCORABLE_CHARS = 20


def _strip_code(text: str) -> str:
    text = _FENCED_CODE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _URL.sub(" ", text)
    return text


def structural_anomaly_score(text: str) -> float | None:
    prose = _strip_code(text)
    non_whitespace = [c for c in prose if not c.isspace()]
    if len(non_whitespace) < MIN_SCORABLE_CHARS:
        return None

    unusual_count = sum(1 for c in non_whitespace if c in _UNUSUAL_SYMBOLS)
    case_flip_count = len(_CASE_FLIP.findall(prose))

    if unusual_count == 0 or case_flip_count == 0:
        return 0.0

    unusual_ratio = unusual_count / len(non_whitespace)
    # Both signals present: score scales with symbol density, capped at
    # 1.0. A single stray symbol plus a single case flip in a long
    # prompt (low ratio) still scores meaningfully above zero, matching
    # what was observed for jb_006 (ratio 0.018, still the real attack).
    return min(1.0, unusual_ratio * 20 + 0.3)
