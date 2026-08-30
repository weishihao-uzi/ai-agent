from evaluate_rag import evaluate_case, retrieval_metrics


def test_retrieval_metrics_use_unique_hits_and_first_rank():
    results = [{"index": 4}, {"index": 2}, {"index": 2}, {"index": 8}]

    metrics = retrieval_metrics(results, [2, 8], top_k=4)

    assert metrics["recall_at_k"] == 1.0
    assert metrics["precision_at_k"] == 0.75
    assert metrics["mrr"] == 0.5


def test_lexical_baseline_respects_metadata_filters():
    documents = [
        {"question": "FastAPI 异步服务", "position_tag": "python_backend", "difficulty": "medium"},
        {"question": "RAG 检索", "position_tag": "ai_application", "difficulty": "medium"},
    ]

    result = evaluate_case(
        {
            "case_id": "filter",
            "query": "FastAPI 异步后端",
            "relevant_indexes": [0],
            "filters": {"position_tag": "python_backend"},
        },
        documents,
        top_k=1,
    )

    assert result["recall_at_k"] == 1.0
    assert result["results"][0]["index"] == 0
