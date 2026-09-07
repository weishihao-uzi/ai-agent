"""
LLM 客户端边界层

单例 ChatOpenAI（包装 DeepSeek，OpenAI 兼容协议）。
独立成模块的原因：position_agent_tools 和 position_agent_service 都要用 get_llm，
而 service 顶部导入 POSITION_AGENT_TOOLS —— 两个模块互相导入会在启动时 ImportError。
"""
from langchain_openai import ChatOpenAI

from app.core.config import settings

_llm: ChatOpenAI | None = None

def get_llm() -> ChatOpenAI:
    """单例 ChatOpenAI 实例（包装 DeepSeek）"""
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.3,
            timeout=120,
        )
    return _llm
