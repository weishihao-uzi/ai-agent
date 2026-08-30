"""Run live LLM judging on one or more deterministic evaluation cases."""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]
BACKEND_ROOT = PROJECT_ROOT / "ai-interview-backend"
sys.path.insert(0, str(BACKEND_ROOT))

CASES_PATH = Path(__file__).parent / "cases.json"


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def assess_against_gold(case: dict, judge_result: dict) -> dict:
    """Compare one model score with the case's expected range and veto rule."""
    expected = case.get("expected", {})
    low, high = expected.get("score_range", [0, 10])
    expected_veto = bool(expected.get("veto", False))
    try:
        score = float(judge_result["score"])
    except (KeyError, TypeError, ValueError):
        return {
            "score": None,
            "range_ok": False,
            "veto_ok": False if expected_veto else None,
            "passed": False,
        }

    range_ok = low <= score <= high
    explicit_veto = judge_result.get("veto")
    if isinstance(explicit_veto, bool):
        observed_veto = explicit_veto
        veto_ok = observed_veto == expected_veto and (not observed_veto or score == 0.0)
    else:
        # Backward-compatible fallback for judges using the old response shape.
        observed_veto = score == 0.0 if expected_veto else None
        veto_ok = observed_veto if expected_veto else None
    return {
        "score": score,
        "expected_range": [low, high],
        "expected_veto": expected_veto,
        "observed_veto": observed_veto,
        "range_ok": range_ok,
        "veto_ok": veto_ok,
        "passed": range_ok and veto_ok is not False,
    }


async def judge_case(case: dict, grounded: bool) -> dict:
    started = time.perf_counter()
    try:
        # Delay backend imports so ``--help`` and argument validation work in
        # environments that only have the offline evaluation dependencies.
        from app.services.client.ai_service import AIService

        result = await AIService.evaluate_answer(
            question=case["question"],
            answer=case["candidate_answer"],
            resume_context={},
            chat_history=[],
            reference_answer=case.get("reference_answer") if grounded else None,
            key_points=case.get("key_points") if grounded else None,
        )
        return {
            "case_id": case["case_id"],
            "ok": True,
            "judge_result": result,
            "gold_eval": assess_against_gold(case, result),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as exc:  # Keep one failed request from hiding other cases.
        return {
            "case_id": case["case_id"],
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }


async def main() -> None:
    parser = argparse.ArgumentParser(description="运行 AI 面试评分的在线 LLM 评估")
    parser.add_argument("--case-id", help="只运行一个 case；默认运行整个评估集")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--ungrounded", action="store_true", help="不向评委提供 reference_answer/key_points")
    parser.add_argument("--model-label", default="configured-model", help="结果中的模型标识，不会覆盖后端配置")
    parser.add_argument("--prompt-version", default="ai_service.evaluate_answer.v3", help="结果中的评分 Prompt 版本")
    parser.add_argument("--output", type=Path, help="将结果写入 JSON 文件")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats 必须大于等于 1")

    cases = load_cases(args.cases)
    if args.case_id:
        cases = [case for case in cases if case["case_id"] == args.case_id]
        if not cases:
            raise ValueError(f"找不到 case: {args.case_id}")

    try:
        # Fail before issuing repeated requests when the selected backend
        # environment is missing a required dependency.
        from app.services.client.ai_service import AIService  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "后端评估依赖未安装，请在 ai-interview-backend/.venv 中执行 "
            "python -m pip install -r requirements.txt，或至少安装 openai、"
            "pydantic-settings、python-dotenv。缺少模块: " + str(exc)
        ) from exc

    records = []
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            result = await judge_case(case, grounded=not args.ungrounded)
            result.update({"repeat": repeat, "grounded": not args.ungrounded})
            records.append(result)

    successful = [record for record in records if record["ok"]]
    scores = [float(record["judge_result"].get("score", 0)) for record in successful]
    gold_evals = [record["gold_eval"] for record in successful]
    veto_evals = [item for item in gold_evals if item.get("expected_veto")]
    veto_case_count = len({record["case_id"] for record in successful if record["gold_eval"].get("expected_veto")})
    case_summaries = []
    for case in cases:
        case_records = [record for record in successful if record["case_id"] == case["case_id"]]
        case_scores = [float(record["judge_result"].get("score", 0)) for record in case_records]
        case_gold = [record["gold_eval"] for record in case_records]
        case_summaries.append(
            {
                "case_id": case["case_id"],
                "run_count": len(case_records),
                "mean_score": round(statistics.mean(case_scores), 3) if case_scores else None,
                "score_stdev": round(statistics.stdev(case_scores), 3) if len(case_scores) > 1 else 0.0,
                "gold_pass_count": sum(item["passed"] for item in case_gold),
                "gold_pass_rate": round(sum(item["passed"] for item in case_gold) / len(case_gold), 4) if case_gold else 0.0,
            }
        )
    summary = {
        "model_label": args.model_label,
        "prompt_version": args.prompt_version,
        "case_count": len(cases),
        "repeats": args.repeats,
        "grounded": not args.ungrounded,
        "run_count": len(records),
        "success_count": len(successful),
        "error_count": len(records) - len(successful),
        "mean_score": round(statistics.mean(scores), 3) if scores else None,
        "score_stdev": round(statistics.stdev(scores), 3) if len(scores) > 1 else 0.0,
        "gold_pass_count": sum(item["passed"] for item in gold_evals),
        "gold_pass_rate": round(sum(item["passed"] for item in gold_evals) / len(gold_evals), 4) if gold_evals else 0.0,
        "gold_range_match_rate": round(sum(item["range_ok"] for item in gold_evals) / len(gold_evals), 4) if gold_evals else 0.0,
        "gold_veto_case_count": veto_case_count,
        "gold_veto_run_count": len(veto_evals),
        "gold_veto_match_rate": round(sum(item["veto_ok"] is True for item in veto_evals) / len(veto_evals), 4) if veto_evals else 0.0,
        "mean_elapsed_ms": round(statistics.mean([r["elapsed_ms"] for r in records]), 1) if records else None,
        "case_summaries": case_summaries,
        "records": records,
    }

    output = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
