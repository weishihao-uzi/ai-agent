from pydantic import BaseModel, Field
from typing import Literal, Optional


class PositionMatchRequest(BaseModel):
    resume_id: int = Field(..., description="已解析完成的简历 ID")
    target_direction: Optional[str] = Field(None, description="用户期望方向，如 'Python 后端'（可选，会传给 Agent 作参考）")


class StartInterviewFromAgentRequest(BaseModel):
    resume_id: int
    position_tag: str
    difficulty: Optional[str] = None
    total_questions: Optional[int] = None


# ── Agent 结构化输出契约 ────────────────────────────────────────────────
# CandidateProfile  = 工具 build_candidate_profile 的输出（含 position_hints）
# MatchResult       = Agent 最终输出 / service 层校验 / 失败重排版，三者共用

class CandidateProfileSummary(BaseModel):
    """最终输出里的画像（System Prompt 的输出 spec 不含 position_hints，故拆出此基类）"""
    experience_level: Literal["campus", "junior", "mid", "senior"] = Field(description="经验层级")
    primary_stack: list[str] = Field(description="核心技术栈，最多 8 个")
    secondary_stack: list[str] = Field(description="次要技术栈")
    project_directions: list[str] = Field(description="项目方向标签，如 电商后端 / AI应用 / 数据分析")
    strong_points: list[str] = Field(description="3 条具体优势")
    weak_points: list[str] = Field(description="3 条具体不足")


class CandidateProfile(CandidateProfileSummary):
    """工具 build_candidate_profile 的输出契约（match_positions 依赖 position_hints）"""
    position_hints: list[str] = Field(
        description="建议匹配的岗位标签，只能取自: python_backend / java_backend / vue_frontend / "
                    "react_frontend / ai_application / fullstack / mobile_android / devops"
    )


class RecommendedPosition(BaseModel):
    position_tag: str = Field(description="岗位内部标识，如 python_backend")
    title: str = Field(description="岗位名称")
    match_score: float = Field(description="匹配度 0-1")
    reasons: list[str] = Field(description="推荐理由，具体可解释")
    missing_skills: list[str] = Field(description="缺失的核心技能")


class MatchResult(BaseModel):
    """Agent 最终输出契约（service 层校验 + 失败重排版共用；额外字段自动忽略）"""
    candidate_profile: CandidateProfileSummary
    recommended_positions: list[RecommendedPosition]
    top_position_focus: dict = Field(description="首选岗位的面试方向（focus_topics / difficulty / 题数等）")
    next_actions: list[str] = Field(description="3 条左右具体可执行的下一步建议")
