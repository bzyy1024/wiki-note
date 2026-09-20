"""
lab05 — 多智能体与编排：Orchestrator-Worker（对应 Part 7）

墨叔：前面 6 个 lab 你一直只有一个 agent 在转——一张纸条、一套工具、一条循环。
这一节我们上一个台阶：当一个任务"大到一个 agent 扛不住、杂到它顾不过来"，
就要用「总控（Orchestrator）+ 工人（Worker）」把活拆开。

这个 lab 要演示的完整链路（类比后端"网关 + 微服务"）：
    用户丢来一个复合任务
      -> 总控把它拆解成几个子任务（一张结构化的"任务看板"）
      -> 总控用 dispatch 工具把子任务派给对应的 worker
      -> 每个 worker 是一个【独立上下文】的 run_loop（故障域天然隔离）
      -> worker 干完只回"摘要"，总控回收
      -> 总控把摘要汇总成最终报告

关键点：
  1. worker 之间互不共享上下文（各自一个 run_loop），A 崩了不影响 B。
  2. worker 回给总控的是"摘要"而非原始满屏输出，否则总控窗口又被撑爆（隔离白拆）。
  3. 嵌套 run_loop 是允许的——总控的循环里套了 worker 的循环，仅此而已。

跑法（默认 mock，零依赖零 key）：
    python main.py
想接真实模型（仅总控走真实 LLM，worker 仍是可替换的 stub）：
    export OPENAI_API_KEY=sk-xxx
    AGENT_MODE=real python main.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common.llm import get_llm, scripted, text_resp, tool_resp, LLMResponse, Message, ToolCall
from common.tools import Tool
from common.runner import run_loop
from common.util import print_step, banner


# =========================================================================
# 1) 工人 Worker 的工具：每个 worker 带【隔离的工具集】（最小权限原则）
#    真实环境这些工具该接数据库 / 绘图库，演示用 stub。
# =========================================================================

def query_sales(region: str) -> str:
    """数据工人的工具：查询指定区域的销售数据（真实环境应查数仓）。"""
    fake_db = {
        "华东": "Q3 营收 1200 万，环比 +8%，退货率 2.1%",
        "华北": "Q3 营收 900 万，环比 -3%，退货率 3.4%",
    }
    return fake_db.get(region, f"{region} 暂无数据")


def make_chart(metric: str) -> str:
    """分析工人的工具：为指定指标生成趋势图（真实环境应落盘图片）。"""
    return f"已生成 '{metric}' 趋势柱状图，关键拐点已标注"


# 每个 worker 是一份独立配置：自己的 system prompt + 自己的工具 + 自己的 mock 剧本。
# 这正对应"微服务只给最小必要接口"——检索 worker 不该拿到绘图工具，反之亦然。
WORKERS = {
    "data_fetcher": {
        "system": "你是【数据工人】，只负责取数/查数，返回简洁数据摘要，不要下结论。",
        "tools": [
            Tool("query_sales", "查询指定区域的销售数据",
                 {"type": "object",
                  "properties": {"region": {"type": "string", "description": "区域名，如 华东"}},
                  "required": ["region"]},
                 query_sales),
        ],
        # 独立上下文的 mock 剧本：第 1 步调工具，第 2 步给"摘要"（不是满屏原始输出）
        "responder": lambda messages, tools, step: (
            tool_resp([("query_sales", {"region": "华东"})]) if step == 1
            else text_resp("华东区 Q3 营收 1200 万，环比 +8%，退货率 2.1%（数据已取）。")
        ),
    },
    "analyst": {
        "system": "你是【分析工人】，只负责对给定数据做总结/画图，返回简明结论。",
        "tools": [
            Tool("make_chart", "为指定指标生成趋势图",
                 {"type": "object",
                  "properties": {"metric": {"type": "string", "description": "指标名，如 华东营收"}},
                  "required": ["metric"]},
                 make_chart),
        ],
        "responder": lambda messages, tools, step: (
            tool_resp([("make_chart", {"metric": "华东营收"})]) if step == 1
            else text_resp("结论：华东区增长稳健（+8%）、退货可控，建议加大投放；已生成营收趋势图。")
        ),
    },
}


# =========================================================================
# 2) run_worker：启动一个"隔离舱"——独立 system prompt + 独立工具 + 独立 run_loop
#    返回的是"摘要字符串"，不是原始细节。这是隔离能否成立的一半。
# =========================================================================

def _worker_on_step(role: str):
    """worker 的每一步轨迹，缩进打印，体现"分层"。"""
    def cb(record):
        s = record.get("step", "?")
        if record.get("tool_calls"):
            for n, a in record["tool_calls"]:
                print(f"        [w:{role}][{s}] think 调工具: {n}({a})")
        elif record.get("tool_result"):
            print(f"        [w:{role}][{s}] act   结果: {record['tool_result']}")
        elif record.get("content"):
            print(f"        [w:{role}][{s}] think 说:  {record['content']}")
    return cb


def run_worker(role: str, task: str) -> str:
    """跑一个隔离的 worker，返回它对子任务的摘要。"""
    cfg = WORKERS[role]
    print(f"    └─ [派活] 启动 worker='{role}'，子任务: {task}")
    llm = get_llm("mock", responder=cfg["responder"])
    out = run_loop(
        llm, cfg["tools"], cfg["system"], task,
        max_steps=8, on_step=_worker_on_step(role),
    )
    print(f"    └─ [回收] worker='{role}' 返回摘要: {out['final']}")
    return out["final"]


# =========================================================================
# 3) 总控的派活工具 dispatch：fn 内部调用 run_worker（嵌套 run_loop 允许）
#    fn 参数名必须匹配 required（subtasks），run_loop 用 **args 调用。
# =========================================================================

def dispatch(subtasks: list) -> str:
    """总控的派活工具：把子任务分发给对应 worker，逐个回收结果并拼回。"""
    results = []
    for st in subtasks:
        role = st["role"]
        task = st["task"]
        summary = run_worker(role, task)
        results.append(f"[{role}] {summary}")
    return "\n".join(results)


ORCH_TOOLS = [
    Tool(
        "dispatch",
        "把拆解出的子任务分派给对应 worker 并回收结果。每项含 role 与 task。",
        {"type": "object",
         "properties": {
             "subtasks": {
                 "type": "array",
                 "description": "子任务列表，每项含 role(worker 名) 与 task(子任务描述)",
                 "items": {"type": "object"},
             }
         },
         "required": ["subtasks"]},
        dispatch,
    ),
]


# =========================================================================
# 4) 总控 orchestrator 的 mock 剧本
#    step 1：收到复合任务 -> 调用 dispatch 把活派出去（上下文里只放"任务看板"）
#    step 2：worker 摘要已回收到上下文 -> 汇总成最终报告
# =========================================================================

def orchestrator_responder(messages, tools, step):
    if step == 1:
        # 总控的"拆解"：把复合任务切成两个异构子任务，派给不同角色的工人
        subtasks = [
            {"role": "data_fetcher", "task": "取华东区 Q3 销售数据并摘要"},
            {"role": "analyst", "task": "基于华东区数据给出结论并生成趋势图"},
        ]
        return tool_resp([("dispatch", {"subtasks": subtasks})])
    # step 2 及以后：worker 结果已回流，总控汇总。此处 mock 直接给出汇总报告。
    return text_resp(
        "【最终报告】\n"
        "· 数据面（来自 data_fetcher）：华东区 Q3 营收 1200 万、环比 +8%、退货率 2.1%，增长稳健。\n"
        "· 分析面（来自 analyst）：建议加大投放，并已生成营收趋势图。\n"
        "· 总控判定：该区域表现健康，可作为下季度重点推广样板。\n"
        "（注：以上结论由两名工人隔离执行后汇总，故障域互不污染。）"
    )


def _orc_on_step(record):
    """总控层面的轨迹，带 [orc] 前缀，与 worker 的缩进区分出层级。"""
    s = record.get("step", "?")
    if record.get("tool_calls"):
        for n, a in record["tool_calls"]:
            print(f"  [orc][{s}] think 模型要求调用: {n}({a})")
    elif record.get("tool_result"):
        print(f"  [orc][{s}] act   工具结果(工人回收):\n        {record['tool_result']}")
    elif record.get("content"):
        print(f"  [orc][{s}] think 模型说: {record['content']}")


# =========================================================================
# 5) 主流程
# =========================================================================

def main():
    mode = os.environ.get("AGENT_MODE", "mock")
    banner(f"lab05 多智能体编排 · Orchestrator-Worker（mode={mode}）")

    # 演示用的复合任务（用户只跟"总控/包工头"对接）
    user_goal = "分析这份华东区销售数据，并给我一份带结论的报告。"
    print(f"[user] {user_goal}\n")

    # 总控的"任务拆解看板"（mock 演示里由 orchestrator_responder 第 1 步产出）
    print("  —— 总控拆解看板 ——")
    print("    ① data_fetcher : 取华东区 Q3 销售数据并摘要   （异构/取数）")
    print("    ② analyst      : 基于数据给结论并生成趋势图    （异构/分析）")
    print("    两个子任务互不依赖，可并行；此处为演示清晰串行派发。\n")

    if mode == "mock":
        llm = get_llm("mock", responder=orchestrator_responder)
    else:
        # 真实模式：仅总控走真实 LLM，worker 仍是我们可替换的 stub（隔离且可控）。
        llm = get_llm("real", model=os.environ.get("AGENT_MODEL", "gpt-4o-mini"))

    out = run_loop(
        llm, ORCH_TOOLS,
        system_prompt="你是总控(Orchestrator)。收到复合任务后，用 dispatch 工具派活给 worker，"
                      "回收摘要后汇总成最终报告。你只做调度与汇总，不直接干细节活。",
        user_input=user_goal,
        max_steps=12, on_step=_orc_on_step,
    )

    banner("最终回答（总控汇总）")
    print(out["final"])
    print(f"\n（总控轨迹 {len(out['trajectory'])} 条记录；worker 轨迹见上方分层缩进）")


if __name__ == "__main__":
    main()
