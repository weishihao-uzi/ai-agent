"""
S2 验收：画像工具 10 连跑，统计 schema 违规率（岗位Agent结构化输出补丁方案.md §8）

用法（backend 根目录）:
    .venv/Scripts/python.exe practice/profile_10runs.py

统计两个口径（区别见方案文档）:
- 硬违规: with_structured_output 内部 pydantic 校验失败 → 工具捕获 → 返回 error dict
- 软违规: 校验通过、但 position_hints 出现在 8 个候选 tag 之外
  （hints 的枚举只写在 description 里，DeepSeek 无 strict:true，schema 管不住它——
   这正是要实测的"指导力"指标）

每次运行消耗一次真实 DeepSeek 调用（deepseek-chat，画像短输出，成本很低）。
跑完把汇总行抄进方案文档 §8。
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 允许从任意目录运行

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")  # backend/.env（同 react_m1.py）

from app.services.client.position_agent_tools import build_candidate_profile

ALLOWED_HINTS = {
    "python_backend", "java_backend", "vue_frontend", "react_frontend",
    "ai_application", "fullstack", "mobile_android", "devops",
}
ALLOWED_LEVELS = {"campus", "junior", "mid", "senior"}

FAKE_RESUME = {
    "name": "wlw",
    "education": {"school": "佳木斯大学", "major": "计算机科学与技术", "grade": "2027届本科"},
    "skills": ["Python", "FastAPI", "LangChain", "Vue", "PostgreSQL", "Redis", "Docker"],
    "experience": [{"company": "某创业公司", "role": "后端开发实习生", "duration": "3个月"}],
    "projects": [{
        "name": "AI 面试 Agent",
        "stack": ["FastAPI", "LangChain", "DeepSeek"],
        "summary": "岗位匹配 Agent + RAG 出题",
    }],
    "summary": "2027届本科生，主力 Python 后端方向，有 AI Agent 项目",
}


async def main(n_runs: int = 10):
    hard_violations = 0   # error dict（pydantic 校验层拦下）
    soft_violations = 0   # hints 越枚举（description 指导层失守）
    latencies = []
    fails = []

    for i in range(1, n_runs + 1):
        t0 = time.perf_counter()
        try:
            res = await build_candidate_profile.ainvoke({"parsed_resume": FAKE_RESUME})
        except Exception as e:
            # 不该发生：工具内已捕获所有异常转 error dict；发生了就是契约破坏
            hard_violations += 1
            fails.append(f"run{i}: 外抛异常 {e}")
            print(f"[{i:02d}] EXCEPTION(契约破坏): {e}")
            continue
        dt = (time.perf_counter() - t0) * 1000

        if isinstance(res, dict) and res.get("error"):
            hard_violations += 1
            fails.append(f"run{i}: {res['error'][:100]}")
            print(f"[{i:02d}] {dt:6.0f}ms  硬违规(error dict): {res['error'][:80]}")
            continue

        level = res.get("experience_level")
        hints = res.get("position_hints", [])
        bad_hints = [h for h in hints if h not in ALLOWED_HINTS]
        level_ok = level in ALLOWED_LEVELS
        latencies.append(dt)

        if bad_hints or not level_ok:
            soft_violations += 1
            fails.append(f"run{i}: level={level} bad_hints={bad_hints}")
            print(f"[{i:02d}] {dt:6.0f}ms  软违规: level={level} bad_hints={bad_hints}")
        else:
            print(f"[{i:02d}] {dt:6.0f}ms  ok: level={level} hints={hints}")

    print("\n" + "=" * 56)
    print(f"共 {n_runs} 次 | 硬违规 {hard_violations} | 软违规 {soft_violations}")
    if latencies:
        print(f"成功 {len(latencies)} 次 | 平均 {sum(latencies)/len(latencies):.0f}ms | "
              f"最慢 {max(latencies):.0f}ms")
    if fails:
        print("违规明细:")
        for f in fails:
            print(f"  - {f}")
    print("\n→ 抄进 岗位Agent结构化输出补丁方案.md §8："
          f"画像 schema 违规率 {hard_violations}/{n_runs}（硬）+ {soft_violations}（软，hints 越枚举）")


if __name__ == "__main__":
    asyncio.run(main())
