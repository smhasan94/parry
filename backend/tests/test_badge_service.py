"""Unit tests for the badge SVG generation service."""

from app.services.badge_service import (
    GRADE_COLORS,
    generate_badge_svg,
    generate_unknown_badge_svg,
)


def test_generates_valid_svg():
    svg = generate_badge_svg("A", 95)
    assert svg.startswith("<svg")
    assert "A (95)" in svg
    assert GRADE_COLORS["A"] in svg


def test_all_grades_have_correct_color():
    for grade, color in GRADE_COLORS.items():
        svg = generate_badge_svg(grade, 50)
        assert color in svg
        assert f"{grade} (50)" in svg


def test_unknown_badge_shows_unknown():
    svg = generate_unknown_badge_svg()
    assert "unknown" in svg


def test_svg_has_aria_label():
    svg = generate_badge_svg("B", 80)
    assert 'aria-label="parry: B (80)"' in svg


def test_svg_has_title():
    svg = generate_badge_svg("C", 65)
    assert "<title>parry: C (65)</title>" in svg


def test_grade_f_uses_red():
    svg = generate_badge_svg("F", 20)
    assert GRADE_COLORS["F"] in svg


def test_unknown_grade_falls_back_to_f_color():
    """A grade not in the map should use the F color as fallback."""
    svg = generate_badge_svg("X", 10)
    assert GRADE_COLORS["F"] in svg
