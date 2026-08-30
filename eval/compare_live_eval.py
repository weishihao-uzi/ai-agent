"""Compare two live evaluation result files without calling an LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_results(grounded: dict[str, Any], ungrounded: dict[str, Any]) -> dict[str, Any]:
    grounded_cases = {item["case_id"]: item for item in grounded.get("case_summaries", [])}
    ungrounded_cases = {item["case_id"]: item for item in ungrounded.get("case_summaries", [])}
    case_ids = sorted(set(grounded_cases) | set(ungrounded_cases))

    case_comparison = []
    for case_id in case_ids:
        g = grounded_cases.get(case_id, {})
        u = ungrounded_cases.get(case_id, {})
        g_mean = g.get("mean_score")
        u_mean = u.get("mean_score")
        case_comparison.append(
            {
                "case_id": case_id,
                "grounded_mean_score": g_mean,
                "ungrounded_mean_score": u_mean,
                "mean_score_delta": round(g_mean - u_mean, 3) if g_mean is not None and u_mean is not None else None,
                "grounded_pass_rate": g.get("gold_pass_rate"),
                "ungrounded_pass_rate": u.get("gold_pass_rate"),
                "pass_rate_delta": round(g.get("gold_pass_rate", 0) - u.get("gold_pass_rate", 0), 4),
                "grounded_score_stdev": g.get("score_stdev"),
                "ungrounded_score_stdev": u.get("score_stdev"),
            }
        )

    def delta(field: str) -> float | None:
        g_value = grounded.get(field)
        u_value = ungrounded.get(field)
        if g_value is None or u_value is None:
            return None
        return round(g_value - u_value, 4)

    return {
        "grounded_file": grounded.get("_source"),
        "ungrounded_file": ungrounded.get("_source"),
        "grounded_prompt_version": grounded.get("prompt_version"),
        "ungrounded_prompt_version": ungrounded.get("prompt_version"),
        "grounded_pass_rate": grounded.get("gold_pass_rate"),
        "ungrounded_pass_rate": ungrounded.get("gold_pass_rate"),
        "gold_pass_rate_delta": delta("gold_pass_rate"),
        "grounded_range_match_rate": grounded.get("gold_range_match_rate"),
        "ungrounded_range_match_rate": ungrounded.get("gold_range_match_rate"),
        "grounded_veto_match_rate": grounded.get("gold_veto_match_rate"),
        "ungrounded_veto_match_rate": ungrounded.get("gold_veto_match_rate"),
        "mean_score_delta": delta("mean_score"),
        "mean_elapsed_ms_delta": delta("mean_elapsed_ms"),
        "case_comparison": case_comparison,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="比较 grounded 与 ungrounded 在线评估结果")
    parser.add_argument("--grounded", type=Path, default=Path("eval/live_grounded.json"))
    parser.add_argument("--ungrounded", type=Path, default=Path("eval/live_ungrounded.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    grounded = load_result(args.grounded)
    ungrounded = load_result(args.ungrounded)
    grounded["_source"] = str(args.grounded)
    ungrounded["_source"] = str(args.ungrounded)
    comparison = compare_results(grounded, ungrounded)
    output = json.dumps(comparison, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
