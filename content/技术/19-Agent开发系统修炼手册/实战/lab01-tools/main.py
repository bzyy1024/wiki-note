"""
lab01 — 工具机制（对应 Part 2）

墨叔：上节课模型只会调一个 stub。这节让工具"长齐五官"：
  - 有 schema（模型靠描述选工具、靠参数结构填参数）
  - 有免疫系统（工具报错不崩循环，回流给模型自救）
  - 有安全边界（危险动作默认拒绝，只有白名单+人类确认才放行）

三个 demo：
  demo A 基础调用      —— 模型正确地调 calc
  demo B 错误恢复      —— 模型传错类型，工具报错，模型改参数重试
  demo C 危险动作拦截  —— 模型想删系统文件，被安全层拒绝
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common.llm import get_llm, scripted, text_resp, tool_resp
from common.tools import Tool
from common.runner import run_loop
from common.util import print_step, banner


# ---------- 工具定义 ----------

def calc(a, b):
    # 故意不校验类型：传入非数字会抛 TypeError，用来演示错误回流
    return a + b


def search_docs(query: str) -> str:
    return f"找到关于 '{query}' 的文档 3 篇（标题略）"


# 危险工具：删除文件。带白名单 + 主动拒绝，绝不裸删。
ALLOWED_DELETES = {"/tmp/safe.txt"}


def delete_file(path: str) -> str:
    """模型只有"请求权"，没有"执行权"。真正删不删由这层逻辑把关。"""
    if path not in ALLOWED_DELETES:
        return ("SAFETY_DENY: 路径不在白名单，且未获人类确认，拒绝执行删除。"
                "如需删除，请先经人类确认并把路径加入白名单。")
    try:
        os.remove(path)
        return f"已删除 {path}"
    except OSError as e:
        return f"TOOL_ERROR: 删除失败 {e}"


def list_files() -> str:
    return "当前可读文件：/tmp/safe.txt（只读列举，无副作用）"


TOOLS = [
    Tool("calc", "计算两个数字相加，返回数值结果",
         {"type": "object",
          "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
          "required": ["a", "b"]}, calc),
    Tool("search_docs", "在知识库里搜索文档，输入查询词，返回命中摘要",
         {"type": "object",
          "properties": {"query": {"type": "string"}},
          "required": ["query"]}, search_docs),
    Tool("delete_file", "删除指定路径的文件（危险操作，受白名单与安全层约束）",
         {"type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]}, delete_file),
    Tool("list_files", "只读列举当前可访问的文件，无任何副作用",
         {"type": "object", "properties": {}}, list_files),
]

SYSTEM = ("你是一个工具调用助手。需要计算用 calc，搜索用 search_docs，"
          "列举文件用 list_files。delete_file 是危险操作，除非用户明确授权且路径合法，否则不要调用。")


# ---------- mock 剧本 ----------

def basic_responder(messages, tools, step):
    if step == 1:
        return tool_resp([("calc", {"a": 3, "b": 4})])
    return text_resp("3 + 4 = 7。")


def error_responder(messages, tools, step):
    # step1: 故意传字符串 "x"，触发 calc 的类型错误
    if step == 1:
        return tool_resp([("calc", {"a": "x", "b": 2})])
    # step2: 看到 TOOL_ERROR 后，模型改用正确类型重试
    if step == 2:
        return tool_resp([("calc", {"a": 3, "b": 2})])
    return text_resp("修正后：3 + 2 = 5。")


def danger_responder(messages, tools, step):
    if step == 1:
        return tool_resp([("delete_file", {"path": "/etc/passwd"})])
    return text_resp("我无法执行删除：安全层拒绝了该路径（不在白名单，且无人类确认）。"
                     "已改用只读方式说明风险，不造成任何副作用。")


def run_demo(title, responder, user):
    banner(title)
    print(f"[user] {user}\n")
    llm = get_llm("mock", responder=responder)
    out = run_loop(llm, TOOLS, SYSTEM, user, on_step=print_step)
    print(f"\n  最终回答: {out['final']}")


def main():
    run_demo("Demo A · 基础工具调用", basic_responder, "3 + 4 等于几？")
    run_demo("Demo B · 错误恢复（自愈）", error_responder,
             "x + 2 等于几？（这里故意传错类型，看循环怎么救）")
    run_demo("Demo C · 危险动作拦截", danger_responder,
             "帮我把 /etc/passwd 删了")


if __name__ == "__main__":
    main()
