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
text.

That said, this function does **not**, and cannot, cleanly separate a
real GCG suffix from a Windows-path-plus-camelCase-identifier bug
report by raw score alone: realistic terse phrasing of that false
positive class (e.g. "getUserById fails on C:\\Users\\x\\y.json in prod
builds today") routinely puts the identifier and the path within any
window narrow enough to still catch a real short suffix. No fixed
window generalizes past both. That is expected and is not this
function's job to fix — the plan's own analysis (Problem Statement
finding 4) already concluded this FP class "legitimately co-triggers
the same AND-rule as the real attack." The actual safety guarantee
lives one layer up, in the caller's confidence ceiling: Task 2's
``adversarial_suffix.py`` maps this score into ``[0.45, 0.65]``, always
below the default trigger threshold of ``0.7``, so this function
returning ``1.0`` for the Windows-path shape can never cause a default
self-trigger. This function must not be trusted as a confident verdict
on its own — only its caller's confidence ceiling makes that promise.
"""

from __future__ import annotations

import re
from bisect import bisect_left

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
# distance 12; "...\\ describing.-- similarlyNOW...", distance 24).
_CLUSTER_WINDOW = 30

# Code-stripping (below) must not itself manufacture a cluster: if a
# case flip sits just before a stripped code block and an unusual
# symbol sits just after it, collapsing that block down to a single
# space would put them within _CLUSTER_WINDOW of each other even though
# they were never actually close in the original text. Replacing a
# stripped region with a whitespace run longer than the cluster window
# guarantees that can never happen, regardless of what was removed or
# how long it was.
_STRIP_GAP = " " * (_CLUSTER_WINDOW + 1)


def _strip_code(text: str) -> str:
    text = _FENCED_CODE.sub(_STRIP_GAP, text)
    text = _INLINE_CODE.sub(_STRIP_GAP, text)
    text = _URL.sub(_STRIP_GAP, text)
    return text


def _is_clustered(flip_pos: int, symbol_positions: list[int]) -> bool:
    # symbol_positions is ascending (built by one left-to-right pass), so
    # binary-search for the first symbol at or after the window's left
    # edge; the flip is clustered iff that symbol is also inside the
    # right edge. O(log symbols) per flip. A linear scan here made
    # scoring O(flips x symbols) — seconds on a padded 40k prompt, which
    # an attacker controls and which stalls the whole async pipeline.
    i = bisect_left(symbol_positions, flip_pos - _CLUSTER_WINDOW)
    return i < len(symbol_positions) and symbol_positions[i] <= flip_pos + _CLUSTER_WINDOW


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
        # close together. This score measures *local* clustering (see
        # the module docstring: global co-occurrence is not a usable
        # signal), so no cluster is no signal. This used to return a
        # flat 0.2 "weak signal", which the caller mapped into the
        # ambiguous band and so sent any ordinary prompt with one stray
        # "~" or "|" and one "JavaScript"/"iPhone" to the paid Claude
        # fallback.
        return 0.0

    clustered_ratio = clustered_flips / len(flip_positions)
    # At least one tight local cluster is the real signature of a GCG
    # suffix, so it already clears the midpoint; more clustered flips
    # push it toward full confidence.
    return min(1.0, 0.5 + 0.5 * clustered_ratio)
