"""Unit tests for the benchmark service."""

from app.services.benchmark_service import (
    BENCHMARK_CORPUS,
    CATEGORIES,
    run_benchmark,
)


def test_corpus_has_entries_for_all_categories():
    corpus_cats = {e["category"] for e in BENCHMARK_CORPUS}
    for cat in CATEGORIES:
        assert cat in corpus_cats, f"Missing corpus entries for category: {cat}"


def test_corpus_entries_have_required_fields():
    for entry in BENCHMARK_CORPUS:
        assert "id" in entry
        assert "category" in entry
        assert "prompt" in entry
        assert "expected_detectors" in entry
        assert isinstance(entry["expected_detectors"], list)


def test_corpus_ids_are_unique():
    ids = [e["id"] for e in BENCHMARK_CORPUS]
    assert len(ids) == len(set(ids)), "Duplicate IDs in benchmark corpus"


def test_run_benchmark_returns_expected_shape():
    result = run_benchmark()
    assert "overall_score" in result
    assert "total_attacks" in result
    assert "total_detected" in result
    assert "categories" in result
    assert "results" in result
    assert isinstance(result["overall_score"], int)
    assert 0 <= result["overall_score"] <= 100


def test_run_benchmark_has_all_categories():
    result = run_benchmark()
    for cat in CATEGORIES:
        assert cat in result["categories"]
        assert "score" in result["categories"][cat]
        assert "detected" in result["categories"][cat]
        assert "total" in result["categories"][cat]


def test_run_benchmark_result_count_matches_corpus():
    result = run_benchmark()
    assert len(result["results"]) == len(BENCHMARK_CORPUS)


def test_clean_prompts_have_no_false_positives():
    """Clean prompts should not trigger any detectors."""
    result = run_benchmark()
    clean_results = [r for r in result["results"] if r["category"] == "clean"]
    for r in clean_results:
        assert r["detected"] is True, f"False positive on {r['id']}: triggered {r['triggered_detectors']}"


def test_overall_score_is_reasonable():
    """The engine should detect the majority of attacks in the corpus."""
    result = run_benchmark()
    assert result["overall_score"] >= 50, f"Overall score too low: {result['overall_score']}%"


def test_prompt_injection_detection_rate():
    result = run_benchmark()
    pi = result["categories"]["prompt_injection"]
    assert pi["score"] >= 60, f"Prompt injection detection too low: {pi['score']}%"


def test_jailbreak_detection_rate():
    result = run_benchmark()
    jb = result["categories"]["jailbreak"]
    assert jb["score"] >= 60, f"Jailbreak detection too low: {jb['score']}%"
