"""
岗位 Agent 结构化输出补丁的单元测试（S5）

覆盖：
1. _parse_final_output 的分层失败路径（解析层 / 校验层 / 重排版层）
2. build_candidate_profile 的错误契约（异常 → error dict，不外抛）

所有测试不触网：重排版路径通过 monkeypatch 假 LLM 注入。
"""
import asyncio
import json

import pytest

from app.schemas.client.position_agent import MatchResult
from app.services.client import position_agent_service as svc
from app.services.client import position_agent_tools as tools


VALID = {
    "candidate_profile": {
        "experience_level": "campus",
        "primary_stack": ["Python", "FastAPI"],
        "secondary_stack": ["Vue"],
        "project_directions": ["AI应用"],
        "strong_points": ["项目完整度高"],
        "weak_points": ["分布式经验少"],
    },
    "recommended_positions": [
        {
            "position_tag": "python_backend",
            "title": "Python 后端工程师",
            "match_score": 0.8,
            "reasons": ["具备 Python/FastAPI 核心技能"],
            "missing_skills": ["Docker"],
        }
    ],
    "top_position_focus": {"position_tag": "python_backend", "focus_topics": ["Python 基础"]},
    "next_actions": ["刷 FastAPI 项目深挖"],
}


def _run(coro):
    return asyncio.run(coro)


class _FakeRepairBoom:
    """假 LLM：with_structured_output 返回的对象 ainvoke 必炸（模拟重排版也失败）"""

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError("repair boom")


class _FakeRepairOk:
    """假 LLM：重排版成功，返回合法 MatchResult"""

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, *args, **kwargs):
        return MatchResult.model_validate(VALID)


# ── 1. 分层失败路径 ─────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("raw", ["", "纯垃圾文本", "Agent stopped due to iteration limit or time limit."])
def test_no_json_content_fails_without_repair(raw, monkeypatch):
    """无 JSON 内容 → 跳过重排版（省一次注定白花的调用），直接 failed"""
    def _must_not_call():
        raise AssertionError("不应创建重排版 LLM")

    monkeypatch.setattr(svc, "get_llm", _must_not_call)
    result = _run(svc.PositionAgentService._parse_final_output(raw))
    assert result.get("error") == "Agent 最终输出格式异常"


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["{}", '截断的{"a":'])
def test_parse_or_validate_failure_then_repair_fails(raw, monkeypatch):
    """{} = 解析成功但校验层失败；截断 JSON = 解析层失败 → 都进重排版 → 重排版也失败 → failed"""
    monkeypatch.setattr(svc, "get_llm", lambda: _FakeRepairBoom())
    result = _run(svc.PositionAgentService._parse_final_output(raw))
    assert result.get("error") == "Agent 最终输出格式异常"
    assert "raw_output" in result


@pytest.mark.unit
def test_valid_output_with_garbage_wrapper_passes(monkeypatch):
    """前缀杂质 + 合法 JSON + 后缀杂质 → raw_decode 提取成功 + 校验成功，不进重排版"""
    monkeypatch.setattr(svc, "get_llm", _FakeRepairBoom)  # 若误入重排版会炸，反向证明没进
    raw = f"好的，以下是结果：\n{json.dumps(VALID, ensure_ascii=False)}\n希望对你有帮助！"
    result = _run(svc.PositionAgentService._parse_final_output(raw))
    assert "error" not in result
    assert result["candidate_profile"]["experience_level"] == "campus"
    assert "repaired" not in result


@pytest.mark.unit
def test_repair_success_marks_repaired(monkeypatch):
    """格式坏但内容在 → 重排版成功 → 带 repaired 标记"""
    raw = f"推荐结果如下：{json.dumps(VALID, ensure_ascii=False)}（以上仅供参考）但缺了外层引号"
    # 构造一个解析必败但含 { 的输入：把 JSON 破坏掉
    raw = "前缀说明文字 { 坏掉的 JSON"
    monkeypatch.setattr(svc, "get_llm", lambda: _FakeRepairOk())
    result = _run(svc.PositionAgentService._parse_final_output(raw))
    assert result.get("repaired") is True
    assert result["candidate_profile"]["experience_level"] == "campus"


# ── 2. 工具错误契约 ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_profile_tool_error_contract(monkeypatch):
    """内层 LLM 异常 → 返回 error dict（主 Agent / match_positions 靠 error key 感知失败）"""

    class _Boom:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("deepseek down")

    monkeypatch.setattr(tools, "_get_profile_llm", lambda: _Boom())
    result = _run(tools.build_candidate_profile.ainvoke({"parsed_resume": {"name": "wlw"}}))
    assert isinstance(result, dict)
    assert "error" in result
    assert "画像生成失败" in result["error"]


@pytest.mark.unit
def test_profile_tool_empty_input():
    """空 parsed_resume → 守卫直接返回 error dict，不触 LLM"""
    result = _run(tools.build_candidate_profile.ainvoke({"parsed_resume": {}}))
    assert result == {"error": "parsed_resume 为空"}
