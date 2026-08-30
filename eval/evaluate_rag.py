"""Offline retrieval evaluation for the interview question-bank RAG."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
DEFAULT_CORPUS_DIR = ROOT.parent / "题库和知识库文档（用于后台上传）"
DEFAULT_CASES = ROOT / "rag_cases.json"


def _tokens(text: str) -> set[str]:
    text = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]+", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.update(run)
        tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _document_text(item: dict[str, Any]) -> str:
    fields = [item.get("question", ""), item.get("reference_answer", "")]
    fields.extend(item.get("key_points") or [])
    fields.extend(item.get("tags") or [])
    return " ".join(str(field) for field in fields)


def lexical_retrieve(
    query: str,
    documents: list[dict[str, Any]],
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a deterministic lexical baseline with optional metadata filters."""
    filters = filters or {}
    query_tokens = _tokens(query)
    candidates = []
    for index, item in enumerate(documents):
        if any(item.get(key) != value for key, value in filters.items() if value is not None):
            continue
        doc_tokens = _tokens(_document_text(item))
        overlap = query_tokens & doc_tokens
        score = len(overlap) / max(len(query_tokens), 1)
        candidates.append(
            {
                "index": index,
                "question": item.get("question", ""),
                "position_tag": item.get("position_tag"),
                "difficulty": item.get("difficulty"),
                "score": round(score, 6),
                "matched_tokens": sorted(overlap),
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["index"]))
    return candidates[:top_k]


def retrieval_metrics(results: list[dict[str, Any]], relevant_indexes: list[int], top_k: int) -> dict[str, float | None]:
    relevant = set(relevant_indexes)
    ranked = [item["index"] for item in results[:top_k]]
    hits = [index for index in ranked if index in relevant]
    first_rank = next((rank for rank, index in enumerate(ranked, start=1) if index in relevant), None)
    return {
        "recall_at_k": round(len(set(hits)) / len(relevant), 4) if relevant else 0.0,
        "precision_at_k": round(len(hits) / len(ranked), 4) if ranked else 0.0,
        "mrr": round(1 / first_rank, 4) if first_rank else 0.0,
        "hit_count": len(set(hits)),
        "result_count": len(ranked),
    }


def evaluate_case(case: dict[str, Any], documents: list[dict[str, Any]], top_k: int = 5) -> dict[str, Any]:
    results = lexical_retrieve(case["query"], documents, top_k=top_k, filters=case.get("filters"))
    metrics = retrieval_metrics(results, case.get("relevant_indexes", []), top_k)
    return {"case_id": case["case_id"], "query": case["query"], "results": results, **metrics}


def evaluate_cases(cases: list[dict[str, Any]], corpora: dict[str, list[dict[str, Any]]], top_k: int = 5) -> dict[str, Any]:
    results = []
    for case in cases:
        documents = corpora[case["corpus"]]
        results.append(evaluate_case(case, documents, top_k=top_k))
    count = len(results)
    return {
        "case_count": count,
        "top_k": top_k,
        "mean_recall_at_k": round(sum(item["recall_at_k"] for item in results) / count, 4) if count else 0.0,
        "mean_precision_at_k": round(sum(item["precision_at_k"] for item in results) / count, 4) if count else 0.0,
        "mean_mrr": round(sum(item["mrr"] for item in results) / count, 4) if count else 0.0,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="运行题库 RAG 的离线检索评估")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k 必须大于等于 1")

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    corpus_names = {case["corpus"] for case in cases}
    corpora = {name: json.loads((args.corpus_dir / name).read_text(encoding="utf-8")) for name in corpus_names}
    summary = evaluate_cases(cases, corpora, top_k=args.top_k)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"cases={summary['case_count']} top_k={summary['top_k']}")
    print(f"Recall@{args.top_k}: {summary['mean_recall_at_k']:.4f}")
    print(f"Precision@{args.top_k}: {summary['mean_precision_at_k']:.4f}")
    print(f"MRR: {summary['mean_mrr']:.4f}")
    for item in summary["results"]:
        print(f"{item['case_id']}: recall={item['recall_at_k']:.2f} mrr={item['mrr']:.2f}")


if __name__ == "__main__":
    main()
