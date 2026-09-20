"""
lab07 — Agent 评测（对应 Part 9 进阶与避坑）

墨叔：前面 6 个 lab 都在"造"。这个 lab 教你"怎么知道它变好了"。
单体测试救不了 agent——它是概率程序，同样的输入两次可能走出不同轨迹。
所以评测要跑一批任务、看通过率，还要看轨迹（步数=成本/效率）。

本 lab 用 mock 演示一套最小的 offline eval：
  - 定义一组任务（输入 + 期望答案里出现的关键词）
  - 逐个跑 agent，检查最终回答是否命中关键词 -> 通过/失败
  - 统计通过率，并对比"弱 system prompt"和"强 system prompt"两版
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common.llm import get_llm, text_resp, tool_resp
from common.tools import Tool
from common.runner import run_loop
from common.util import banner


# ---------- 工具（和前面 lab 一样的极简集） ----------

def get_weather(city: str) -> str:
    return f"{city} 晴，22℃"


def calc(a: int, b: int) -> int:
    return a + b


def search_docs(query: str) -> str:
    return f"关于 {query} 的文档若干篇"


TOOLS = [
    Tool("get_weather", "查询城市天气",
         {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
         get_weather),
    Tool("calc", "加法", {"type": "object",
         "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}, calc),
    Tool("search_docs", "搜索文档",
         {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
         search_docs),
]


# ---------- 任务对应的 mock 剧本（按 step 返回） ----------

def weather_r(m, t, s):
    if s == 1:
        return tool_resp([("get_weather", {"city": "北京"})])
    return text_resp("北京今天晴，22℃。")


def calc_r(m, t, s):
    if s == 1:
        return tool_resp([("calc", {"a": 3, "b": 4})])
    return text_resp("3+4=7。")


def search_v1_r(m, t, s):
    # 弱版：直接凭记忆答，没走 search_docs，缺关键词"文档"
    if s == 1:
        return text_resp("Go 是一门编程语言。")


def search_v2_r(m, t, s):
    # 强版：先检索再答，命中"文档"
    if s == 1:
        return tool_resp([("search_docs", {"query": "Go"})])
    return text_resp("关于 Go 的文档已检索到，Go 是编译型语言，适合高并发。")


# 两版任务集：前两个任务两版都过，第三个任务 V1 漏检索（不过）、V2 过
TASKS_V1 = [
    {"name": "天气查询", "user": "北京天气", "responder": weather_r, "expect": ["晴", "22"]},
    {"name": "加法计算", "user": "3+4 等于几", "responder": calc_r, "expect": ["7"]},
    {"name": "检索问答", "user": "讲讲 Go", "responder": search_v1_r, "expect": ["文档"]},
]
TASKS_V2 = [
    {"name": "天气查询", "user": "北京天气", "responder": weather_r, "expect": ["晴", "22"]},
    {"name": "加法计算", "user": "3+4 等于几", "responder": calc_r, "expect": ["7"]},
    {"name": "检索问答", "user": "讲讲 Go", "responder": search_v2_r, "expect": ["文档"]},
]

SYSTEM_V1 = "你是一个助手。"
SYSTEM_V2 = "你是一个助手。需要实时数据先查工具，搜索类问题先用 search_docs 检索再回答，最后给明确结论。"


def run_eval(tasks, system):
    """跑一组任务，返回 (逐条结果, 通过率)。"""
    rows = []
    for task in tasks:
        llm = get_llm("mock", responder=task["responder"])
        out = run_loop(llm, TOOLS, system, task["user"], max_steps=6)
        final = out["final"]
        passed = all(k in final for k in task["expect"])
        rows.append({
            "name": task["name"], "passed": passed, "steps": len(out["trajectory"]),
            "final": final,
        })
    rate = sum(1 for r in rows if r["passed"]) / len(rows)
    return rows, rate


def print_report(title, rows, rate):
    banner(title)
    print(f"{'任务':<10}{'通过':<6}{'步数':<6}最终回答")
    print("-" * 70)
    for r in rows:
        mark = "✅" if r["passed"] else "❌"
        print(f"{r['name']:<10}{mark:<6}{r['steps']:<6}{r['final']}")
    print(f"\n通过率: {rate*100:.0f}%  ({sum(1 for r in rows if r['passed'])}/{len(rows)})")


def main():
    banner("Lab07 · Agent 评测（对应 Part 9）")

    rows1, rate1 = run_eval(TASKS_V1, SYSTEM_V1)
    rows2, rate2 = run_eval(TASKS_V2, SYSTEM_V2)

    print_report("评估版本 V1（弱 system prompt）", rows1, rate1)
    print()
    print_report("评估版本 V2（强 system prompt：先检索再答）", rows2, rate2)

    print("\n=== 结论 ===")
    print(f"从 V1 的 {rate1*100:.0f}% 提升到 V2 的 {rate2*100:.0f}%，")
    print("靠的是在 system prompt 里强制'检索类问题先 search_docs'——")
    print("这正是 Part 9.1 说的：用 eval 把'玄学调参'变成'可度量迭代'。")


if __name__ == "__main__":
    main()
