"""Offline evaluation for the AI interview answer judge.

The evaluator is deliberately deterministic. It checks a case against the
case's rubric so that changes to the live LLM judge can be compared against a
stable local baseline.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
CASES_PATH = ROOT / "cases.json"


def _normalise(text: str) -> str:
    """Make simple Chinese/English synonym checks insensitive to formatting."""
    text = str(text or "").lower()
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[，。；、：？！,.;:!?()（）\[\]{}\"'`]", "", text)


def _matches(answer: str, patterns: list[str]) -> bool:
    normalised = _normalise(answer)
    return any(_normalise(pattern) in normalised for pattern in patterns if pattern)


def _score_rubric(answer: str, rubric: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    dimensions: list[dict[str, Any]] = []
    total = 0.0

    for dimension in rubric.get("dimensions", []):
        checks = dimension.get("checks", [])
        max_points = float(dimension.get("max_points", 0))
        total_weight = sum(float(check.get("weight", 1)) for check in checks)
        matched_weight = 0.0
        matched_checks: list[str] = []
        missing_checks: list[str] = []

        for check in checks:
            check_id = check.get("id", "unnamed_check")
            if _matches(answer, check.get("patterns", [])):
                matched_weight += float(check.get("weight", 1))
                matched_checks.append(check_id)
            else:
                missing_checks.append(check_id)

        score = max_points * matched_weight / total_weight if total_weight else 0.0
        total += score
        dimensions.append(
            {
                "id": dimension.get("id", "unnamed_dimension"),
                "name": dimension.get("name", dimension.get("id", "")),
                "score": round(score, 2),
                "max_points": max_points,
                "matched_checks": matched_checks,
                "missing_checks": missing_checks,
            }
        )

    return round(total, 1), dimensions


def _legacy_score(answer: str, case: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    """Keep old case files usable while they are migrated to ``rubric``."""
    checks = case.get("concept_checks", [])
    if checks:
        matched: list[str] = []
        missing: list[str] = []
        total_weight = sum(float(check.get("weight", 1)) for check in checks)
        matched_weight = 0.0
        for check in checks:
            if _matches(answer, check.get("patterns", [])):
                matched.append(check["id"])
                matched_weight += float(check.get("weight", 1))
            else:
                missing.append(check["id"])
        score = 10 * matched_weight / total_weight if total_weight else 0.0
        return round(score, 1), matched, missing

    required = case.get("must_include", [])
    matched = [item for item in required if _matches(answer, [item])]
    missing = [item for item in required if item not in matched]
    score = 10 * len(matched) / len(required) if required else 0.0
    return round(score, 1), matched, missing


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    answer = case.get("candidate_answer", "")
    rubric = case.get("rubric") or {}

    if rubric.get("dimensions"):
        score, dimensions = _score_rubric(answer, rubric)
        matched = [check for dimension in dimensions for check in dimension["matched_checks"]]
        missing = [check for dimension in dimensions for check in dimension["missing_checks"]]
    else:
        score, matched, missing = _legacy_score(answer, case)
        dimensions = []

    forbidden = rubric.get("veto_patterns", case.get("forbidden_claims", []))
    triggered = [pattern for pattern in forbidden if _matches(answer, [pattern])]
    veto = bool(triggered)
    if veto:
        score = 0.0

    expected = case.get("expected", {})
    low, high = expected.get("score_range", [0, 10])
    expected_veto = bool(expected.get("veto", False))

    return {
        "case_id": case["case_id"],
        "score": score,
        "veto": veto,
        "matched": matched,
        "missing": missing,
        "dimensions": dimensions,
        "triggered_forbidden_claims": triggered,
        "expected_range": [low, high],
        "expected_veto": expected_veto,
        "range_ok": low <= score <= high,
        "veto_ok": veto == expected_veto,
        "passed": low <= score <= high and veto == expected_veto,
    }


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [evaluate_case(case) for case in cases]
    total = sum(result["score"] for result in results)
    count = len(results)
    pass_count = sum(result["passed"] for result in results)
    return {
        "case_count": count,
        "total_score": round(total, 1),
        "average_score": round(total / count, 2) if count else 0.0,
        "pass_count": pass_count,
        "pass_rate": round(pass_count / count, 4) if count else 0.0,
        "veto_count": sum(result["veto"] for result in results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 AI 面试评分的离线 Rubric 评估")
    parser.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    parser.add_argument("--cases", type=Path, default=CASES_PATH, help="评估集 JSON 路径")
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    summary = evaluate_cases(cases)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    for result in summary["results"]:
        print(f"\n[{result['case_id']}] score={result['score']}/10 veto={result['veto']} passed={result['passed']}")
        print(f"matched: {result['matched']}")
        print(f"missing: {result['missing']}")
        print(f"expected range: {result['expected_range']} veto={result['expected_veto']}")

    print(
        f"\nTOTAL: {summary['total_score']:.1f}/{summary['case_count'] * 10:.1f} "
        f"| pass={summary['pass_count']}/{summary['case_count']} "
        f"| veto={summary['veto_count']}"
    )


if __name__ == "__main__":
    main()
