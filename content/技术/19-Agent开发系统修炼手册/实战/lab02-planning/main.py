"""
lab02 — 规划与分解（对应教程 Part 3）

墨叔：前两节课你学会了"模型 + 循环 + 工具"。但当你把 agent 丢去干一件
稍大的事（比如"整理我今天的待办并提醒我"），它容易走一步看一步、中途跑偏。
这节课要给它装上三件兵器：
  1. Plan-and-Execute —— 先画地图再走路：让模型先产出一份"可检查的步骤清单"，
     再逐步执行。计划成了显式的中间产物，人能审、能改、出错了能重画。
  2. 任务分解粒度 —— 计划里的每一步，要"刚好能独立完成、有明确可验证产出"。
     太粗则单步不可验证、易幻觉；太细则步骤爆炸、上下文被噪声淹没。
  3. Critic 反思循环 —— 每步产出后，先让"审稿人"自我评估这步对不对；
     发现跑偏就修正/重来，而不是闭眼往下走。

本课用两个 run_loop 演示（这是最清晰、最贴近真实架构的写法）：
  loop 1（规划器）：模型只"想"、不调工具，产出步骤清单文本。
  loop 2（执行器）：模型逐步骤调工具落地，并在关键节点插入 Critic 自检。

仅用 Python 标准库，mock 零依赖、零 API key 即可跑。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)   # 即 实战/ 目录
sys.path.insert(0, ROOT)

from common.llm import get_llm, scripted, text_resp, tool_resp, LLMResponse, Message, ToolCall
from common.tools import Tool
from common.runner import run_loop
from common.util import print_step, banner


# =====================================================================
# 工具：模拟"子任务执行"。每个工具返回一个字符串结果，喂回模型。
# 注意：这些工具只是 stub，真实环境换成查数据库/发消息/调 API 即可。
# =====================================================================

def search_docs(query: str) -> str:
    # stub：真实环境这里该查你的笔记/日历/工单系统
    return (f"检索到关于『{query}』的今日备忘 3 条："
            f"① 写完周报 ② 评审小李的 PR ③ 下午预约牙医")


def draft_summary(text: str) -> str:
    # 起草待办清单。注意：第一次（没自检前）我们故意漏掉"提醒"动作，
    # 用来演示 Critic 怎么发现问题。真实模型也会这样：先写得不全。
    return f"待办草稿：{text}"


def send_reminder(msg: str) -> str:
    # stub：真实环境这里该调消息/日历 API
    return f"提醒已发送：{msg}"


def critic_check(output: str) -> str:
    """
    确定性 Critic（硬事实，不是模型自评！）

    墨叔：这是本节课最关键的一招。critic_check 不是一个"让模型自己夸自己"
    的软检查，而是一个**用代码事实说话**的确定性校验——就像你 CI 里的单测。
    它只检查产出里有没有满足任务的"硬契约"（必须含待办、必须含提醒动作）。
    满足→"通过"，不满足→明确列出问题，逼执行器回去改。

    这正是 Part 3.4 的精髓：模型挑方向，测试定生死。Critic 循环里"必然对不对"
    的判断，必须交给确定性代码，不能问模型"你对了吗"。
    """
    problems = []
    if "待办" not in output and "任务" not in output:
        problems.append("未列出具体待办项")
    if "提醒" not in output:
        problems.append("缺少『提醒』动作，不符合『整理并提醒我』的任务要求")
    if problems:
        return "Critic 未通过：" + "；".join(problems) + "。请修正后重试。"
    return "Critic 通过：产出满足任务要求（OK）。"


TOOLS = [
    Tool("search_docs", "检索今日待办与日程，输入查询词，返回备忘列表",
         {"type": "object",
          "properties": {"query": {"type": "string", "description": "查询词"}},
          "required": ["query"]}, search_docs),
    Tool("draft_summary", "基于检索结果起草待办清单草稿，输入文本，返回草稿",
         {"type": "object",
          "properties": {"text": {"type": "string", "description": "草稿内容"}},
          "required": ["text"]}, draft_summary),
    Tool("critic_check", "对当前产出做确定性自检：是否含待办项与提醒动作。通过返回 OK，否则列出问题",
         {"type": "object",
          "properties": {"output": {"type": "string", "description": "待检查的产出文本"}},
          "required": ["output"]}, critic_check),
    Tool("send_reminder", "发送提醒消息，输入消息内容，返回发送回执",
         {"type": "object",
          "properties": {"msg": {"type": "string", "description": "提醒内容"}},
          "required": ["msg"]}, send_reminder),
]


# =====================================================================
# 系统提示词
# =====================================================================

SYSTEM_PLANNER = (
    "你是一个规划器（planner）。你只负责『想全局、列清单』，**这一轮不调用任何工具**，"
    "不被任何细节带偏。请基于用户目标产出一份有序步骤清单，每步含：动作 + 预期产出，"
    "且每步都『模型能独立完成、有明确可验证产出』（刚好粒度，不要一步干太多，也不要碎到原子操作）。"
)

SYSTEM_EXECUTOR = (
    "你是一个执行器（executor）。请严格对照已给出的计划逐步执行，每步调用合适的工具。"
    "关键规则：每次 draft_summary 产出后，必须先调用 critic_check 做自检；"
    "若 Critic 未通过，必须回到 draft_summary 修正后再过一次 Critic，直到通过才能进入 send_reminder。"
)


# =====================================================================
# 规划器 responder：只输出计划文本，不调工具（保持俯瞰视角）
# =====================================================================

def planner_responder(messages, tools, step):
    if messages[-1].role == "user":
        # 规划这一轮：纯文本输出步骤清单，不碰工具
        plan = (
            "计划如下（已按『刚好粒度』设计，每步独立、有可验证产出）：\n"
            "  ① search_docs：检索今日待办与日程 → 产出备忘列表\n"
            "  ② draft_summary：基于备忘起草待办清单草稿 → 产出草稿文本\n"
            "  ③ critic_check：对草稿做确定性自检（是否含待办项 + 提醒动作）"
            "→ 不通过则回到 ② 修正，通过才继续\n"
            "  ④ send_reminder：草稿自检通过后，发送提醒消息 → 产出发送回执\n"
            "  ⑤ 汇总：输出最终总结"
        )
        return text_resp(plan)
    # 计划已给出，循环结束（text_resp 无 tool_calls，run_loop 视为最终回答）
    return text_resp("（计划已生成，交执行器执行）")


# =====================================================================
# 执行器 responder：看"上一条消息"决定下一步，串起完整的
# 计划 → 多步执行 → Critic 自检 → 修正 → 总结 轨迹
# =====================================================================

def executor_responder(messages, tools, step):
    last = messages[-1]

    # 初始：用户下达任务 → 第①步，检索待办
    if last.role == "user":
        return tool_resp([("search_docs", {"query": "今天的待办与日程"})])

    # 工具结果回流，按工具名分支
    if last.role == "tool":
        name = last.name

        if name == "search_docs":
            # 第②步：基于检索结果起草草稿（故意先漏掉"提醒"，留给 Critic 抓）
            return tool_resp([("draft_summary",
                              {"text": "① 写完周报 ② 评审小李的 PR ③ 下午预约牙医"})])

        if name == "draft_summary":
            # 草稿已产出 → 进入第③步，交给确定性 Critic 自检
            return tool_resp([("critic_check", {"output": last.content})])

        if name == "critic_check":
            if "OK" in last.content:
                # 自检通过 → 第④步，发送提醒
                return tool_resp([("send_reminder",
                                  {"msg": "今日待办：写完周报、评审小李PR、下午预约牙医，请按时完成"})])
            else:
                # 自检未通过（第一次草稿缺"提醒"）→ 回到 ② 修正，补上提醒动作
                return tool_resp([("draft_summary",
                                  {"text": "① 写完周报 ② 评审小李的 PR ③ 下午预约牙医。"
                                           "已为你设置提醒：18 点前完成前两项并预约牙医。"})])
        if name == "send_reminder":
            # 第⑤步：所有步骤通过，汇总总结（不再调工具 → 循环结束）
            return text_resp(
                "已完成：整理出今日 3 项待办，经 Critic 自检发现初稿漏了提醒动作并已修正，"
                "现已发送提醒。任务结束。"
            )

    # 兜底，避免任何意外下死循环
    return text_resp("（兜底）任务结束。")


def main():
    mode = os.environ.get("AGENT_MODE", "mock")

    banner("lab02 · 规划与分解（Plan-and-Execute + 粒度 + Critic）")

    # ---------- 第一幕：规划器产出计划（可检查的中间产物） ----------
    banner("第一幕 · 规划器：先画地图")
    plan_llm = get_llm("mock", responder=planner_responder)
    plan_out = run_loop(plan_llm, [], SYSTEM_PLANNER,
                        "请帮我整理今天的待办并提醒我。", on_step=print_step)
    plan_text = plan_out["final"]
    print(f"\n  [plan] 规划器给出的步骤清单：\n{plan_text}")

    # ---------- 第二幕：执行器按计划逐步执行，并在关键节点插 Critic ----------
    banner("第二幕 · 执行器：照图走路（含 Critic 自检）")
    # 把计划注入执行器的上下文，让它"每步对齐计划"
    exec_system = SYSTEM_EXECUTOR + f"\n\n当前计划：\n{plan_text}"
    exec_llm = get_llm("mock", responder=executor_responder)
    exec_out = run_loop(exec_llm, TOOLS, exec_system,
                        "请按计划整理我今天的待办并提醒我。",
                        max_steps=12, on_step=print_step)

    banner("最终结果")
    print(exec_out["final"])
    print(f"\n（执行轨迹共 {len(exec_out['trajectory'])} 条记录）")

    # ---------- 第三幕：规划失败的几种形态（代码外，README 详述） ----------
    banner("第三幕 · 规划失败的 5 种形态（见 README 3.5 节）")
    print("  本课 mock 跑通的是『健康路径』。真实世界里计划会翻车：")
    print("    ① 计划过于乐观  ② 步骤依赖没理清  ③ 卡死循环")
    print("    ④ 目标漂移      ⑤ 工具失败无备选")
    print("  对应解法：侦察预算、步骤接口契约、失败记忆+上限、范围围栏、fallback。")


if __name__ == "__main__":
    main()
