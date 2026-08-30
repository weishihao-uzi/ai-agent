import json
from pathlib import Path

from evaluate_cases import evaluate_case, evaluate_cases
from compare_live_eval import compare_results
from run_live_eval import assess_against_gold


ROOT = Path(__file__).parent


def test_seed_cases_all_match_their_gold_ranges():
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    summary = evaluate_cases(cases)

    assert summary["case_count"] == 9
    assert summary["pass_count"] == summary["case_count"]
    assert summary["veto_count"] == 2


def test_veto_overrides_positive_dimension_score():
    case = {
        "case_id": "veto",
        "candidate_answer": "项目评分准确率达到99%",
        "expected": {"score_range": [0, 0], "veto": True},
        "rubric": {
            "dimensions": [
                {"id": "quality", "max_points": 10, "checks": [{"id": "score", "patterns": ["评分"]}]}
            ],
            "veto_patterns": ["评分准确率达到99%"],
        },
    }

    result = evaluate_case(case)

    assert result["score"] == 0.0
    assert result["veto"] is True
    assert result["passed"] is True


def test_matching_ignores_spacing_and_punctuation():
    case = {
        "case_id": "normalise",
        "candidate_answer": "题库 RAG，便于评分。",
        "expected": {"score_range": [10, 10], "veto": False},
        "rubric": {
            "dimensions": [
                {
                    "id": "quality",
                    "max_points": 10,
                    "checks": [{"id": "all", "patterns": ["题库RAG便于评分"]}],
                }
            ],
            "veto_patterns": [],
        },
    }

    assert evaluate_case(case)["score"] == 10.0


def test_live_score_is_compared_with_gold_range_and_veto():
    case = {"expected": {"score_range": [9, 10], "veto": False}}
    result = assess_against_gold(case, {"score": 9.5})

    assert result["range_ok"] is True
    assert result["veto_ok"] is None
    assert result["passed"] is True


def test_live_veto_case_requires_zero_score():
    case = {"expected": {"score_range": [0, 0], "veto": True}}

    assert assess_against_gold(case, {"score": 0})["passed"] is True
    assert assess_against_gold(case, {"score": 2})["passed"] is False


def test_live_explicit_veto_is_checked_separately_from_score():
    case = {"expected": {"score_range": [0, 0], "veto": True}}

    result = assess_against_gold(case, {"score": 0, "veto": True})
    assert result["observed_veto"] is True
    assert result["veto_ok"] is True
    assert result["passed"] is True


def test_compare_results_reports_grounding_lift():
    grounded = {
        "prompt_version": "v2",
        "gold_pass_rate": 0.8,
        "gold_range_match_rate": 0.8,
        "gold_veto_match_rate": 1.0,
        "mean_score": 5.0,
        "mean_elapsed_ms": 1000.0,
        "case_summaries": [{"case_id": "a", "mean_score": 8.0, "gold_pass_rate": 1.0, "score_stdev": 0.0}],
    }
    ungrounded = {
        "prompt_version": "v2",
        "gold_pass_rate": 0.5,
        "gold_range_match_rate": 0.5,
        "gold_veto_match_rate": 0.5,
        "mean_score": 4.0,
        "mean_elapsed_ms": 1200.0,
        "case_summaries": [{"case_id": "a", "mean_score": 6.0, "gold_pass_rate": 0.0, "score_stdev": 1.0}],
    }

    result = compare_results(grounded, ungrounded)

    assert result["gold_pass_rate_delta"] == 0.3
    assert result["mean_elapsed_ms_delta"] == -200.0
    assert result["case_comparison"][0]["mean_score_delta"] == 2.0
