# AI 面试评估

这里是第一版离线评估集和在线 LLM 评估入口，当前聚焦“题库参考答案/采分点能否让回答评分更可靠”，以及题库 RAG 的检索质量。

## 离线 Rubric

离线评估不调用模型，适合检查评估集和评分器本身：

```bash
python -B eval/evaluate_cases.py
python -B eval/evaluate_cases.py --json > eval/offline_result.json
```

每个 case 的 `rubric.dimensions` 定义可解释的得分维度，`veto_patterns` 定义一票否决的无依据声明。`expected.score_range` 和 `expected.veto` 是金标准，修改 Rubric 或样例后必须先保证离线评估全部通过。

## 在线基线与 A/B

在线评估需要后端依赖和模型 API 配置。使用 `--repeats 3` 可观察评分波动；去掉参考答案和采分点可作为未加固的对照组：

```bash
python -B eval/run_live_eval.py --repeats 3 --model-label deepseek --prompt-version v3 --output eval/live_grounded.json
python -B eval/run_live_eval.py --repeats 3 --ungrounded --model-label deepseek --prompt-version v3 --output eval/live_ungrounded.json
```

也可以用 `--case-id scoring_grounded_correct` 只运行一个样例。脚本会记录每次调用是否成功、模型返回的评分和耗时，并把分数自动与 case 的 `expected.score_range`、`expected.veto` 对照，汇总 `gold_pass_rate` 和逐题重复波动；当前 `AIService` 没有暴露 token usage，因此结果不会伪造成本字段。

比较两组结果：

```bash
python -B eval/compare_live_eval.py --output eval/live_comparison.json
```

重点查看 `gold_pass_rate_delta` 和 `case_comparison`，不要只比较总体平均分。

## 题库 RAG 检索评估

`rag_cases.json` 当前包含 20 个查询，固定相关题目和岗位/难度过滤条件；`evaluate_rag.py` 提供一个无 API、无数据库依赖的词法检索基线，用来先验证评估集和指标计算：

```bash
python -B eval/evaluate_rag.py
python -B eval/evaluate_rag.py --top-k 10 --json > eval/rag_lexical_baseline.json
```

输出包括 `Recall@K`、`Precision@K` 和 `MRR`。这不是线上 pgvector 的最终结果；下一步应使用同一批 `rag_cases.json` 调用 `QuestionBankService.retrieve_questions`，记录真实 embedding、过滤条件、相似度和召回排名，再复用这些指标进行对比。

真实 pgvector 评估（需要在后端虚拟环境中运行，并确保 PostgreSQL/pgvector、题库 embedding 和 DashScope Key 已配置）：

```bash
cd ai-interview-backend
python -B ../eval/run_live_rag_eval.py --top-k 5 --min-score 0.7 --output ../eval/rag_pgvector_baseline.json
```

首次验证可以只跑一个查询：

```bash
python -B ../eval/run_live_rag_eval.py --case-id rag_private_knowledge --top-k 5 --min-score 0.7
```

脚本会记录每个查询的真实相似度、召回题目、过滤违规和耗时；数据库不可用时会保留逐 case 错误，不会把失败伪装成 0 分。
