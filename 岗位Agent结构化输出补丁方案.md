# 岗位匹配 Agent 结构化输出补丁方案（最小改动版）

> 2026-09-06 定稿。生产代码补丁：两处插入 `with_structured_output`，Agent 框架零改动。
> 定位：Q4/Q12 的源头治理（档位一完整版）。M3 Pipeline 重写是练习线的独立里程碑，与本补丁不冲突——补丁讲"稳"，M3 讲"判断"，双素材。

---

## 1. 解决什么问题

| 问题 | 触发路径 | 现状行为 |
|---|---|---|
| **画像字段错位（Q4）** | `build_candidate_profile` 的 LLM 输出字段名/枚举错位（如 `primary_stacks`、`experience_level="应届"`），`match_positions` 全部 `or []` 兜底 | 不报错，返回 **3 条 match_score 全 0.0 的"推荐"**（`position_agent_tools.py:123-160`） |
| **最终输出格式失败（Q12）** | Agent 最后一轮不返回 tool_calls 直接输出文本；或文本内嵌了能解析但形状不对的 JSON 片段 | 解析失败 → 500；**解析"成功"但字段全错 → 静默脏数据**（`position_agent_service.py:172-183`） |

两个问题的共同根因：**LLM 输出没有 schema 约束，格式保证靠 System Prompt 文字约定 + 事后 `_extract_json` 碰运气**。补丁把这两处的格式保证下沉到 API 的工具 schema 契约。

## 2. 方案总览

```
不改：create_tool_calling_agent / AgentExecutor / System Prompt / 其余 4 个工具
新增：两处 with_structured_output 插入点

插入点 1（治 Q4）：build_candidate_profile 内层 LLM 调用 → schema 化
    工具签名、返回契约、被调用方式全部不变
插入点 2（治 Q12）：service 层解析失败时 → 补一次"重排版"调用
    仅失败时触发，一次为限
```

**一条死路（记录在案，防止回头再试）**：Agent 循环的最终输出**接不上** `with_structured_output`——它会把 `tool_choice` 锁死在 schema 工具上，agent 每轮只能调 schema 工具、调不了 5 个真工具；且其返回的 Runnable 没有 `bind_tools`，塞进 `create_tool_calling_agent` 直接挂。最终答案的 schema 保证只能靠插入点 2 事后修复，或等 M3 重写。

**画像保持 LLM，不规则化**：`parsed_resume` 已是上游 LLM 产物，经验层级/技术栈分级规则化可行，但 strong/weak_points 和项目方向的语义判断是这一步的核心价值；且"5 个全确定性工具 + LLM 循环路由"会让 Agent 的存在更站不住。

## 3. 改动一：画像内层调用 schema 化

**位置**：`position_agent_tools.py` 的 `build_candidate_profile`（68-118 行区域）

**schema 定义**（放在 `app/schemas/client/position_agent.py`，pydantic v2 `BaseModel`，不要用 `langchain_core.pydantic_v1`）：

```python
from typing import Literal
from pydantic import BaseModel, Field

class CandidateProfile(BaseModel):
    experience_level: Literal["campus", "junior", "mid", "senior"]
    primary_stack: list[str] = Field(description="核心技术栈，最多 8 个")
    secondary_stack: list[str]
    project_directions: list[str]
    strong_points: list[str] = Field(description="3 条具体优势")
    weak_points: list[str] = Field(description="3 条具体不足")
    position_hints: list[str] = Field(description="只能取自: python_backend / java_backend / vue_frontend / react_frontend / ai_application / fullstack / mobile_android / devops")

class RecommendedPosition(BaseModel):
    position_tag: str
    title: str
    match_score: float
    reasons: list[str]
    missing_skills: list[str]

class MatchResult(BaseModel):
    candidate_profile: CandidateProfile
    recommended_positions: list[RecommendedPosition]
    top_position_focus: dict          # 先宽松；收紧留到 M3
    next_actions: list[str]
```

> `MatchResult` 与将来 M2 手写循环的 `final_answer` 工具共用同一份定义——单一事实源从现在开始建。
>
> **实施时的关键细化（2026-09-06）**：Agent System Prompt 的最终输出 spec 里 `candidate_profile` **不含 `position_hints`**（那只是工具内层画像的字段）。若 `MatchResult` 直接要求 `position_hints`，每次正常输出都会校验失败、全量触发重排版。落地为继承两模型：`CandidateProfileSummary`（6 字段，MatchResult 用）继承出 `CandidateProfile`（+ `position_hints`，工具 schema 用）。

**改动前必做（S2 第 0 步）：抽 `llm.py` 防循环导入**

`position_agent_service.py:18` 顶部导入了 `POSITION_AGENT_TOOLS`；工具文件若再从 service 顶部导入 `get_llm` → **启动即 ImportError**。解法：新建 `app/services/client/llm.py`，把 `get_llm()` 和 `_llm` 单例整个搬过去，service / tools 都从它导入（service 里删掉原定义）。懒导入（函数体内 import）也能跑但是 code smell，不采用。

**改动后的工具内部结构**（伪码，实现自己写）：

```python
from app.services.client.llm import get_llm
_profile_llm = get_llm().with_structured_output(CandidateProfile)   # 返回新 Runnable，不动单例

raw 逻辑：
  1. 原 system prompt 保留评估标准说明，删掉"必须返回纯 JSON"段（schema 取代文字约定）
  2. profile = await _profile_llm.ainvoke(messages)     # 失败抛 OutputParserException
  3. except → return {"error": "画像生成失败，原因 ..."}   # 错误契约不变，主 Agent 行为不变
  4. return profile.model_dump()    # ⚠️ 返回的是 pydantic 对象，喂回 agent 前必须转 dict
```

**坑清单**：
- `with_structured_output` 默认 `method="function_calling"`（langchain-openai 0.2.14），DeepSeek 支持 FC，可用；`strict: true` DeepSeek 不支持——schema 是强指导不是硬约束，所以第 3 步的失败分支不能省
- 想加保险可 `.with_retry(stop_after_attempt=2)`，超过就落 error 分支，不做无限重试
- 原 118 行的 `{"error": "AI 输出解析失败", "raw": ...}` 分支整个删除（`_extract_json` 不再出现在此工具）
- 工具 docstring 不用改（对外契约没变）

## 4. 改动二：最终输出失败重排版

**位置**：`position_agent_service.py` 的 `run_agent`（172-183 行区域）

**触发条件**：`_extract_json` 抛异常 **或** `MatchResult.model_validate(result)` 失败——两种失败统一进入修复路径：

```python
触发时（仅一次）：
  repair_llm = get_llm().with_structured_output(MatchResult)
  try:
      profile = await repair_llm.ainvoke(
          "将以下 Agent 输出整理为 JSON 结构化结果，不得新增、不得改写事实信息：\n" + raw_output
      )                       # ↑ prompt 必须含 "JSON" 字样：这是 DeepSeek json_mode 的触发条件
      result = profile.model_dump()      # ⚠️ 返回的是 pydantic 对象，先转 dict 才能加标记
      result["repaired"] = True          # 可观测标记
  except Exception:
      走现有 failed 分支，返回 {"error": "Agent 最终输出格式异常", ...}
```

**设计要点**：
- 这是**无状态重排版**，不需要重建会话历史——要重排的内容全在 raw_output 里（intermediate_steps 重建是"内容缺失"时的重手法，本补丁不用）
- "内容没写完"的场景（模型提前收工、raw_output 里根本没有岗位信息）重排版也救不了——校验失败照旧 failed，边界清晰
- **省一次白花调用**：`raw_output` 里连 `{` 都没有（典型：iteration-limit 那句固定字符串）时直接走 failed，跳过修复调用
- `repaired: True` 的出现率记进日志，这是后续判断"要不要上 M3 根治"的量化依据

## 5. 明确不做（scope guard）

- 不动 Agent / AgentExecutor / System Prompt（最小 diff 原则；Prompt 里"必须输出纯 JSON"段落留着无害）
- 不做 PII 脱敏（Q10/Q11 的日志与 intermediate_steps 泄露是独立工单，别混进本补丁）
- 不动 `verbose=True` 开关（同上，独立工单）
- 不删 langchain 依赖（本补丁反而依赖 `langchain-openai`，已在 requirements）
- 不做四层语义降级（degraded 态没有前端消费路径之前不做）

## 6. 实施顺序与验收

按顺序做，每步验收过了再做下一步：

- [x] **S1 schema 落地**：三个 pydantic 模型进 `app/schemas/client/position_agent.py`；`python -c` 导入无报错；`CandidateProfile.model_json_schema()` 能打印（✅ 2026-09-06，实际落地 4 个模型）
- [x] **S2 改动一**：工具 2 换 `_profile_llm`（先做上面的 `llm.py` 抽取）；✅ 2026-09-07 十连跑完成：硬违规 0/10、软违规 0/10，均值 2750ms（脚本 `practice/profile_10runs.py`，数据见 §8）
- [x] **S3 改动二**：service 层加 model_validate + 修复调用；✅ 2026-09-07 注入测试通过：尾部逗号破坏的 JSON → 修复路径出 `repaired: True`，内容零改写（positions/next_actions 原样保留），仅 1 次修复调用
- [x] **S4 回归**：✅ 2026-09-07 `/match` 端到端经真实 UI 全链路走通（简历上传 → 岗位匹配 → 开面 → 报告评分），页面正常渲染无报错。当时未专门留存 app 日志的"无 repaired/重排版字样"确认，补验一条命令即可：`docker logs ai-interview-app 2>&1 | grep -iE "repaired|重排版"`（无输出 = 正常路径零修复；容器当日起未重建，日志仍含当日记录）。正常路径 10 连跑量级未做，M3 立项需要时再补
- [x] **S5 测试入库**：✅ 2026-09-06 `tests/test_position_agent_output_parsing.py` 9 用例全绿（分层失败路径 ×3、杂质包裹正常通过、重排版成功/失败、工具错误契约 ×2，被测对象为 service 层解析+校验组合函数；其中 `"{}"` → 解析成功但校验失败 → failed，是"脏数据拦截"的直接证明）
- [x] **S6 数据记录**：✅ 2026-09-07 已录入 §8（画像 schema 违规率、S3 注入、端到端状态）；正常路径修复触发率 10 连跑留待 M3 立项需要时补测

## 7. 面试话术（30 秒）

> "我们的岗位 Agent 有两个格式风险：画像字段错位会导致下游静默打出全零分推荐，最终输出格式坏会 500。我的最小改动方案是两处 `with_structured_output`：嵌套的画像调用本来就是单发单收，schema 化后 Q4 在源头堵死；最终输出在解析或校验失败时补一次无状态的重排版调用，只重排版不重跑，一次为限。Agent 框架一行没动——因为我用裸 SDK 手写过等价循环，知道哪层能插哪层不能：agent 循环的 LLM 必须保持可绑多工具的裸模型，with_structured_output 锁 tool_choice 的机制决定了它进不了循环，只能放在循环外的单发调用上。"

## 8. 实测数据（S6 填写）

| 指标 | 数值 | 备注 |
|---|---|---|
| 画像 schema 违规率（S2） | **硬 0/10，软 0/10**（2026-09-07 实测） | hints 全部精确落在枚举内（python_backend / ai_application ×10）；DeepSeek 无 strict 下 description 指导力实测有效 |
| 修复路径触发率（S4，人为注入除外） | 端到端 ×1 完成，触发与否未查日志（补验命令见 §9） | 2026-09-07 真实 UI 全链路 1 次，结果正常渲染；10 连跑未做，M3 立项需要时再补 |
| 正常路径延迟变化 | 画像单次调用均值 2750ms，最慢 5383ms（n=10；首轮为单例冷启动） | 端到端 `/match` 整体在真实 UI 正常响应，无感知异常 |
| S3 注入测试（尾部逗号破坏 JSON，内容完整） | ✅ repaired=True，内容零改写 | 2026-09-07 真实修复调用 1 次，2026-09-06 单测另有假 LLM 覆盖 9 用例 |

## 9. 实施记录（2026-09-06 实施，2026-09-07 收尾完成：S1–S6 全部关闭）

**代码改动**：
- `app/schemas/client/position_agent.py`：+4 模型（`CandidateProfileSummary` / `CandidateProfile` / `RecommendedPosition` / `MatchResult`）
- `app/services/client/llm.py`：**新建**，`get_llm()` 单例从 service 迁入（断循环导入）
- `app/services/client/position_agent_tools.py`：工具 2 换 `with_structured_output(CandidateProfile)`（懒加载 `_get_profile_llm()`），System Prompt 删 JSON 模板段留评估标准；`AIService` import 移除；错误契约不变（`error` key）
- `app/services/client/position_agent_service.py`：`get_llm` 定义移除改导入；原解析块换成 `_parse_final_output()`（解析 → 校验 → 无 `{` 跳过修复 → 一次性重排版带 `repaired` 标记）
- `tests/test_position_agent_output_parsing.py`：**新建**，9 个用例全绿（分层失败路径 ×3、杂质包裹正常通过、重排版成功/失败、工具错误契约 ×2）

**验证结果**：py_compile 4 文件通过；导入链通过（5 工具注册、无循环导入）；pytest 9/9 passed；真实 DeepSeek 冒烟 1 次成功。

**留给用户的收尾**：
- [x] ~~S2 的 10 连跑~~ ✅ 2026-09-07：硬 0/10、软 0/10，均值 2750ms（`practice/profile_10runs.py`）
- [x] ~~S3 注入测试~~ ✅ 2026-09-07：坏 JSON → repaired=True，内容零改写（本机直调 `_parse_final_output`）
- [x] ~~S4 回归~~ ✅ 2026-09-07：端到端经真实 UI 全链路走通（上传 → 匹配 → 开面 → 报告）。日志级确认未当场留存，可补一条：`docker logs ai-interview-app 2>&1 | grep -iE "repaired|重排版"`（无输出 = 正常路径零修复）
- [x] ~~git 提交~~ ✅ 2026-09-07：`01be6f4`（feat：补丁 3 文件 + llm.py + 9 测试 + 本文档 + .gitignore 增补）、`0dfaed3`（docs：题库RAG代码逻辑图 + practice 笔记），已推送 origin（weishihao-uzi/ai-agent）；kb-rag 因内嵌独立 .git（5 个里程碑提交）暂未收录，待定 subtree 合并或重新导入

**环境备注**：本地 `.venv`（Python 3.13）装不了 `langchain==0.3.7`（其 `numpy<2` 上限在 3.13 无 wheel），本地升到 `langchain==0.3.27`；**requirements.txt 未动**，Docker 内（低版本 Python）仍用 0.3.7。两版本在本次用到的 API（`with_structured_output` / `create_tool_calling_agent`）上行为一致；正式回归（S4）已在 Docker 环境完成（2026-09-07，VM 后端）。
