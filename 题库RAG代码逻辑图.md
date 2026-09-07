# 题库 RAG 代码逻辑图

> 范围：**题库 RAG**（`question_bank` 表 + pgvector 检索 + 出题/评分消费），不含知识库 RAG（`knowledge_*` 表 / Milvus 那条链路）。
> 向量化模型两边共用同一个 DashScope `text-embedding-v3`（1024 维），但存储与检索完全独立。

## 总逻辑图

```mermaid
flowchart TD
    %% ══ ① 管理端：题库写入与向量化 ══
    subgraph INGEST["① 管理端写入 · api/backoffice/v1/question_bank.py"]
        direction TB
        A1["POST /question-bank 新增单题"] --> S_CREATE["QuestionBankService.create"]
        A2["PUT /{id} 更新题目"] --> S_UPDATE["QuestionBankService.update"]
        A3["POST /batch-import 批量导入"] --> S_IMPORT["先全部入库 embedding=NULL<br/>再提交 Celery 异步向量化"]
        A4["POST /reindex-all 全量重建"] --> S_REINDEX["Celery: reindex_all_sync<br/>每 50 题一批"]
        A5["POST /test-retrieve 召回测试"] -.-> RET
        S_IMPORT --> S_BATCH["Celery: batch_embed_sync"]
        S_REINDEX --> S_BATCH
        S_CREATE --> EMBTXT["_build_embedding_text<br/>题面 + 「参考答案：」+ 参考答案 拼接"]
        S_UPDATE -->|"改了 question / reference_answer 才触发"| EMBTXT
    end

    EMBTXT --> EMB1["embed_text 单条向量化"]
    S_BATCH --> EMB2["embed_texts 批量向量化<br/>每批 25 条"]
    EMB1 --> EMB0["embedding.py<br/>DashScopeEmbeddings<br/>text-embedding-v3 · 1024 维"]
    EMB2 --> EMB0

    %% ══ ② 存储层 ══
    subgraph STORE["② 存储 · PostgreSQL + pgvector"]
        T1[("question_bank 表<br/>embedding Vector(1024)<br/>embedding_text 原文留存<br/>过滤字段: is_active / position_tag / difficulty<br/>元数据: key_points / tags / source / use_count")]
    end
    EMB0 -->|"向量 + 原文写入"| T1

    %% ══ ③ 面试出题：检索 + 三分支生成 ══
    subgraph GEN["③ RAG 出题 · services/client/interview_service.py"]
        direction TB
        G0["start_interview<br/>校验简历 status=completed"] --> G1["json.loads 得到 parsed_resume"]
        G1 --> G2["_build_retrieval_query<br/>目标岗位 + 简历前 8 个技能拼接"]
        G2 --> G3["recall_k = total × RECALL_FACTOR(2)"]
        G3 --> RET["QuestionBankService.retrieve_questions"]
        RET --> G5{"召回数 ≥ 目标题数?"}
        G5 -->|"否: 放宽 position_tag=None<br/>同参数重检一次, 按 id 去重合并"| G6{"重新判断 cnt"}
        G5 -->|"是"| B1
        G6 -->|"cnt ≥ total"| B1["分支A 充分 · select_and_adapt_questions<br/>LLM 从候选挑 N 题, 难度递进排序, 可微调措辞<br/>必须保留 bank_id + reference_answer<br/>source=from_bank"]
        G6 -->|"0 < cnt < total"| B2["分支B 不足 · generate_with_seeds<br/>题库题作种子必须全部保留<br/>AI 补齐剩余题并自写参考答案<br/>source=from_bank / ai_fallback 混合"]
        G6 -->|"cnt = 0"| B3["分支C 为空 · generate_questions<br/>纯 AI 生成 legacy 兜底<br/>source=ai_fallback · bank_id=None"]
    end

    RET -->|"query 先向量化(cosine_distance 检索)"| EMB0
    T1 -->|"候选题列表 + similarity"| RET

    B1 --> P1["questions_data(JSON) 存入 Interview 记录"]
    B2 --> P1
    B3 --> P1
    P1 --> P2["increment_use_count<br/>被选中题 use_count + 1"]
    P2 --> P3["第 1 题存为 interviewer 消息<br/>返回 first_question"]

    %% ══ ④ 面试评分：题库答案注入 ══
    subgraph EVAL["④ 评分消费 · 题库答案注入"]
        direction TB
        E1["submit_answer / submit_answer_stream"] --> E2["从 questions_data 取当前题<br/>reference_answer + key_points"]
        E2 --> E3["evaluate_answer(_stream)<br/>提示词注入【参考答案要点】+【关键采分点】"]
        E3 --> E4["评分按采分点覆盖率校准<br/>编造数据 → veto=true 计 0 分"]
    end
    P3 --> E1
```

## 检索 SQL 细节（`retrieve_questions`）

| 环节 | 实现 |
|---|---|
| query 向量化 | `embed_text(query)`，与入库同一模型 |
| 相似度 | pgvector `embedding.cosine_distance(query_vec)` |
| 阈值 | `distance ≤ 1 - QUESTION_BANK_MIN_SCORE(0.7)`，即相似度 ≥ 0.7 |
| 过滤 | `is_active = true`、`embedding IS NOT NULL`、`position_tag.contains(目标岗位)`（contains 模糊匹配）、`difficulty = 请求难度` |
| 排序/截断 | `ORDER BY distance LIMIT k`（k = 题数 × 2） |
| 返回 | `{id, category, position_tag, difficulty, question, reference_answer, key_points, similarity, source: from_bank}` |

## 关键参数（`app/core/config.py`）

- `QUESTION_BANK_MIN_SCORE = 0.7` —— 相似度门槛，低于不召回
- `QUESTION_BANK_RECALL_FACTOR = 2` —— 召回倍数（要 10 题先检 20 条）
- `QUESTION_BANK_TOP_K = 20` —— 管理端召回测试默认 k

## 文件地图

| 环节 | 文件 |
|---|---|
| 管理端 API（CRUD / 批量导入 / 重建 / 召回测试） | `ai-interview-backend/app/api/backoffice/v1/question_bank.py` |
| 题库服务（向量化时机 + pgvector 检索） | `ai-interview-backend/app/services/backoffice/question_bank_service.py` |
| 表模型 | `ai-interview-backend/app/models/question_bank.py` |
| Embedding 封装（DashScope，25 条/批） | `ai-interview-backend/app/services/common/embedding.py` |
| RAG 出题编排（query 构造 + 三分支） | `ai-interview-backend/app/services/client/interview_service.py` |
| LLM 出题三分支 + 评分注入 | `ai-interview-backend/app/services/client/ai_service.py` |
| Celery 异步向量化任务 | `ai-interview-backend/app/schedule/jobs/knowledge_tasks.py` |
