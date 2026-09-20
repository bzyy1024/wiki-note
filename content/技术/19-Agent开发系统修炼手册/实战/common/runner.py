"""
common/runner.py — 统一的 Agent Loop

墨叔：所有 lab 的核心都是这一个循环：

    observe（看当前消息） -> think（模型产出） -> act（执行工具） -> 再 observe ...

直到模型不再要求调工具（给出最终回答），或步数到上限。

把循环单独抽出来，是因为它是 agent 的"心跳"。你后面看到的规划、记忆、
多智能体，全是在这个心跳外面套壳——核心永远是这一圈。
"""
from __future__ import annotations

from typing import Callable, List, Optional

from .llm import Message
from .tools import find_tool


def run_loop(llm, tools, system_prompt: str, user_input: str,
             max_steps: int = 12, on_step: Optional[Callable] = None) -> dict:
    """
    跑一个完整 agent 回合。

    参数：
      llm          : 一个 BaseLLM（MockLLM 或 RealLLM）
      tools        : Tool 列表（可为空）
      system_prompt: 系统提示词（agent 的"宪法"）
      user_input   : 用户的初始指令
      max_steps    : 最多循环几步（防止跑飞）
      on_step      : 每步回调，用于打印轨迹/日志

    返回：
      {"final": str, "trajectory": [每步记录]}
    """
    messages: List[Message] = [
        Message("system", system_prompt),
        Message("user", user_input),
    ]
    trajectory = []
    final = None

    for step in range(1, max_steps + 1):
        resp = llm.chat(messages, tools)
        record = {
            "step": step,
            "content": resp.content,
            "tool_calls": [(tc.name, tc.arguments) for tc in resp.tool_calls],
        }
        trajectory.append(record)

        if on_step:
            on_step(record)

        if not resp.tool_calls:
            # 模型不再要求调工具 -> 这是最终回答
            final = resp.content
            break

        # 把 assistant 的"调工具意图"写回消息（真实 API 需要这条上下文才能接 tool 结果）
        messages.append(Message("assistant", resp.content, tool_calls=resp.tool_calls))

        # 逐个执行工具，把结果作为 tool 消息追加进上下文
        for tc in resp.tool_calls:
            tool = find_tool(tools, tc.name)
            if tool is None:
                result = f"TOOL_ERROR: 未知工具 {tc.name}"
            else:
                result = tool.run(tc.arguments)
            messages.append(Message("tool", result, tool_call_id=tc.id, name=tc.name))
            trajectory.append({
                "step": step,
                "tool_result": f"{tc.name}({tc.arguments}) -> {result}",
            })

    if final is None:
        final = "（达到最大步数仍未给出最终回答）"
    return {"final": final, "trajectory": trajectory}
