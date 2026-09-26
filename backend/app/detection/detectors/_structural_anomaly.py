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
identifiers mentioned in prose. Global presence of both isn't safe
either — a Windows path (backslashes near the end of a sentence) and a
camelCase identifier (earlier in the same sentence) both "exist" in the
text without being part of the same adversarial span. What a real GCG
suffix looks like is a *dense, local* cluster: the case flip and an
unusual symbol sit within a few characters of each other, because both
are artifacts of the same broken detokenization run. So this function
measures local co-occurrence directly — for each case flip, whether an
unusual symbol appears within ``_CLUSTER_WINDOW`` characters of it —
rather than just checking that both signals appear somewhere in the
text. Even so, this function must not be trusted as a confident
verdict. Its caller (``adversarial_suffix.py``) deliberately keeps this
in the pipeline's ambiguous-confidence band rather than self-triggering,
because a realistic developer bug report (a Windows path plus a
camelCase function name in the same sentence) can still score above
zero.
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
# there isn't enough text for either signal to mean anything. Must stay
# above the non-whitespace length of any prompt whose only content is a
# stripped fenced-code-block frame (e.g. "Here's the fix: / Does this
# look right?", 31 chars) and below the shortest prompt that should
# still be scored.
MIN_SCORABLE_CHARS = 35

# A case flip and an unusual symbol within this many characters of each
# other are treated as the same local cluster. Chosen empirically: wide
# enough to span a short adversarial fragment ("...\ + similarlyNow...",
# distance 12; "...\\ describing.-- similarlyNOW...", distance 24) but
# narrower than the gap in the Windows-path-plus-camelCase false
# positive, where the flips in `getUserById` sit 42+ characters from the
# backslashes in the path.
_CLUSTER_WINDOW = 30


def _strip_code(text: str) -> str:
    text = _FENCED_CODE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _URL.sub(" ", text)
    return text


def _is_clustered(flip_pos: int, symbol_positions: list[int]) -> bool:
    return any(abs(flip_pos - s) <= _CLUSTER_WINDOW for s in symbol_positions)


def structural_anomaly_score(text: str) -> float | None:
    prose = _strip_code(text)
    non_whitespace = [c for c in prose if not c.isspace()]
    if len(non_whitespace) < MIN_SCORABLE_CHARS:
        return None

    symbol_positions = [i for i, c in enumerate(prose) if c in _UNUSUAL_SYMBOLS]
    flip_positions = [m.start() for m in _CASE_FLIP.finditer(prose)]

    if not symbol_positions or not flip_positions:
        return 0.0

    clustered_flips = sum(1 for f in flip_positions if _is_clustered(f, symbol_positions))
    if clustered_flips == 0:
        # Both signals are present somewhere in the text, but never
        # close together — the Windows-path-plus-camelCase shape. Score
        # low rather than zero: the co-occurrence is still a weak signal
        # worth surfacing to the ambiguous-confidence LLM fallback, just
        # not one this function should be confident about.
        return 0.2

    clustered_ratio = clustered_flips / len(flip_positions)
    # At least one tight local cluster is the real signature of a GCG
    # suffix, so it already clears the midpoint; more clustered flips
    # push it toward full confidence.
    return min(1.0, 0.5 + 0.5 * clustered_ratio)
