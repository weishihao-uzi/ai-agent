"""Run the RAG cases against the real QuestionBankService retrieval path."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parents[1]
BACKEND_ROOT = PROJECT_ROOT / "ai-interview-backend"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "eval"))

from evaluate_rag import retrieval_metrics


CASES_PATH = Path(__file__).parent / "rag_cases.json"
CORPUS_DIR = PROJECT_ROOT / "题库和知识库文档（用于后台上传）"


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpora(cases: list[dict[str, Any]], corpus_dir: Path) -> dict[str, list[dict[str, Any]]]:
    names = {case["corpus"] for case in cases}
    return {name: json.loads((corpus_dir / name).read_text(encoding="utf-8")) for name in names}


def map_retrieved_questions(rows: list[dict[str, Any]], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index_by_question = {item.get("question"): index for index, item in enumerate(documents)}
    mapped = []
    for row in rows:
        item = dict(row)
        item["index"] = index_by_question.get(row.get("question"))
        mapped.append(item)
    return mapped


async def run_case(case: dict[str, Any], documents: list[dict[str, Any]], db: Any, top_k: int, min_score: float) -> dict[str, Any]:
    from app.services.backoffice.question_bank_service import QuestionBankService

    started = time.perf_counter()
    filters = case.get("filters") or {}
    rows = await QuestionBankService.retrieve_questions(
        query=case["query"],
        db=db,
        k=top_k,
        position_tag=filters.get("position_tag"),
        difficulty=filters.get("difficulty"),
        min_score=min_score,
    )
    mapped = map_retrieved_questions(rows, documents)
    metrics = retrieval_metrics(mapped, case.get("relevant_indexes", []), top_k)
    filter_violations = [
        row["index"]
        for row in mapped
        if (filters.get("position_tag") and row.get("position_tag") != filters["position_tag"])
        or (filters.get("difficulty") and row.get("difficulty") != filters["difficulty"])
    ]
    return {
        "case_id": case["case_id"],
        "query": case["query"],
        "filters": filters,
        "retrieved": mapped,
        **metrics,
        "filter_ok": not filter_violations,
        "filter_violations": filter_violations,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="运行题库 RAG 的真实 pgvector 检索评估")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--corpus-dir", type=Path, default=CORPUS_DIR)
    parser.add_argument("--case-id", help="只运行一个 case，先用于验证 embedding 和数据库链路")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.top_k < 1 or not 0 <= args.min_score <= 1:
        parser.error("--top-k 必须大于等于 1，--min-score 必须在 0 到 1 之间")

    cases = load_cases(args.cases)
    if args.case_id:
        cases = [case for case in cases if case["case_id"] == args.case_id]
        if not cases:
            raise ValueError(f"找不到 case: {args.case_id}")
    corpora = load_corpora(cases, args.corpus_dir)
    try:
        from app.core.config import settings
        from app.db.base import close_db_engine, get_session_local
        from app.services.backoffice.question_bank_service import QuestionBankService  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(f"后端依赖未安装，无法运行真实 RAG 评估。缺少模块: {exc}") from exc

    records = []
    try:
        async with get_session_local()() as db:
            for case in cases:
                try:
                    record = await run_case(case, corpora[case["corpus"]], db, args.top_k, args.min_score)
                    record["ok"] = True
                except Exception as exc:  # Keep one failed query visible without hiding other cases.
                    record = {"case_id": case["case_id"], "ok": False, "error": f"{type(exc).__name__}: {exc}"}
                records.append(record)
    finally:
        await close_db_engine()

    successful = [record for record in records if record["ok"]]
    summary = {
        "retrieval_mode": "question_bank_service_pgvector",
        "embedding_model": settings.KNOWLEDGE_EMBEDDING_MODEL,
        "top_k": args.top_k,
        "min_score": args.min_score,
        "case_count": len(cases),
        "success_count": len(successful),
        "error_count": len(records) - len(successful),
        "mean_recall_at_k": round(statistics.mean([r["recall_at_k"] for r in successful]), 4) if successful else None,
        "mean_precision_at_k": round(statistics.mean([r["precision_at_k"] for r in successful]), 4) if successful else None,
        "mean_mrr": round(statistics.mean([r["mrr"] for r in successful]), 4) if successful else None,
        "filter_pass_rate": round(sum(r["filter_ok"] for r in successful) / len(successful), 4) if successful else None,
        "mean_elapsed_ms": round(statistics.mean([r["elapsed_ms"] for r in successful]), 1) if successful else None,
        "records": records,
    }
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
