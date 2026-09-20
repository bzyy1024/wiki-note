"""
common/tools.py — 工具定义与执行

墨叔：工具就是"模型能指挥、但真正干活的是你的代码"的那一层。
这里只定义两件事：
  1. 工具长什么样（名字 / 描述 / 参数 JSON schema）
  2. 怎么执行它，把结果包成字符串喂回模型

关键认知：模型永远不直接执行代码。它只输出"我想调 calc，参数是 {a:1,b:2}"，
真正跑代码的是你的循环。这层隔离，是后面所有安全机制（沙箱、确认、权限）
的物理基础——模型只有"请求权"，没有"执行权"。
"""
from __future__ import annotations

from typing import Callable, List


class Tool:
    def __init__(self, name: str, description: str, parameters: dict, fn: Callable):
        self.name = name                  # 工具名（模型靠它选工具）
        self.description = description    # 描述（决定模型调得准不准，极重要）
        self.parameters = parameters      # JSON Schema，描述参数结构
        self.fn = fn                     # 真正干活的 Python 函数

    def run(self, arguments: dict) -> str:
        """执行工具，返回字符串结果（喂回模型）。"""
        try:
            return str(self.fn(**arguments))
        except Exception as e:
            # 错误处理是 agent 的免疫系统：工具报错也要包成字符串回流给模型，
            # 让模型自己判断怎么救，而不是让整个循环崩溃。
            return f"TOOL_ERROR: {type(e).__name__}: {e}"


def to_openai_schema(tool: Tool) -> dict:
    """转成 OpenAI function-calling 需要的 schema 格式。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def find_tool(tools: List[Tool], name: str) -> Tool:
    for t in tools:
        if t.name == name:
            return t
    return None
