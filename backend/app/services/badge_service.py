"""Security score badge SVG generator.

Produces shields.io-style SVG badges showing an agent's current
health grade (A/B/C/D/F). Designed for embedding in READMEs and docs.
"""

GRADE_COLORS = {
    "A": "#22c55e",  # green-500
    "B": "#84cc16",  # lime-500
    "C": "#eab308",  # yellow-500
    "D": "#f97316",  # orange-500
    "F": "#ef4444",  # red-500
}

_LABEL = "parry"
_LABEL_WIDTH = 42
_GRADE_WIDTH = 38
_TOTAL_WIDTH = _LABEL_WIDTH + _GRADE_WIDTH
_HEIGHT = 20
_FONT = "font-family='DejaVu Sans,Verdana,Geneva,sans-serif' font-size='11'"


def generate_badge_svg(grade: str, score: int) -> str:
    """Return a shields.io-style SVG badge for the given grade."""
    color = GRADE_COLORS.get(grade, GRADE_COLORS["F"])
    grade_text = f"{grade} ({score})"
    # Widen the grade section for the score text
    grade_w = 56
    total_w = _LABEL_WIDTH + grade_w

    aria = f"{_LABEL}: {grade_text}"
    lx = _LABEL_WIDTH + grade_w / 2
    lx2 = _LABEL_WIDTH / 2
    shadow = 'fill="#010101" fill-opacity=".3"'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{total_w}" height="{_HEIGHT}" role="img" aria-label="{aria}">\n'
        f"  <title>{_LABEL}: {grade_text}</title>\n"
        f'  <linearGradient id="s" x2="0" y2="100%">\n'
        f'    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>\n'
        f'    <stop offset="1" stop-opacity=".1"/>\n'
        f"  </linearGradient>\n"
        f'  <clipPath id="r">'
        f'<rect width="{total_w}" height="{_HEIGHT}" rx="3" fill="#fff"/></clipPath>\n'
        f'  <g clip-path="url(#r)">\n'
        f'    <rect width="{_LABEL_WIDTH}" height="{_HEIGHT}" fill="#555"/>\n'
        f'    <rect x="{_LABEL_WIDTH}" width="{grade_w}" height="{_HEIGHT}" fill="{color}"/>\n'
        f'    <rect width="{total_w}" height="{_HEIGHT}" fill="url(#s)"/>\n'
        f"  </g>\n"
        f'  <g fill="#fff" text-anchor="middle" {_FONT}>\n'
        f'    <text x="{lx2}" y="14" {shadow}>{_LABEL}</text>\n'
        f'    <text x="{lx2}" y="13">{_LABEL}</text>\n'
        f'    <text x="{lx}" y="14" {shadow}>{grade_text}</text>\n'
        f'    <text x="{lx}" y="13">{grade_text}</text>\n'
        f"  </g>\n"
        f"</svg>"
    )


def generate_unknown_badge_svg() -> str:
    """Badge shown when the agent doesn't exist or badge is disabled."""
    return (
        generate_badge_svg("?", 0)
        .replace("? (0)", "unknown")
        .replace(GRADE_COLORS.get("F", ""), "#9ca3af")
    )
