"""
lab06 — 迷你 Claude Code（Capstone，对应 Part 8 蓝图）

墨叔：这是实战的压轴。前面学的工具、规划、记忆、工程化，今天全部焊在一起，
造一个"能改 bug 的迷你 Claude Code"。

关键设计：用一个**内存文件系统（沙箱）**当代码库，绝不碰你真实的磁盘。
这样 demo 既真实（有 search/read/write/run 全流程），又零副作用、可复现。

端到端任务：用户报了一个 issue —— login 函数忘了 return，调用方拿到 None 崩溃。
mini-claude 的标准动作链（呼应 Part 8.5）：
    search（定位文件）-> read（读源码）-> 定位 bug -> write（修复）-> run（跑测试）-> 总结
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common.llm import get_llm, text_resp, tool_resp, Message, LLMResponse
from common.tools import Tool
from common.runner import run_loop
from common.util import print_step, banner

# ---------- 沙箱：内存文件系统（替代真实磁盘，安全可复现） ----------

FS = {
    "src/auth.py": (
        "def login(username):\n"
        "    user = db.find(username)\n"
        "    # BUG: 忘记 return user，调用方拿到 None\n"
        "    print('login done')\n"
    ),
    "src/db.py": (
        "def find(u):\n"
        "    return {'name': u}\n"
    ),
}

FIXED_AUTH = (
    "def login(username):\n"
    "    user = db.find(username)\n"
    "    return user\n"
)


# ---------- 工具执行层（Part 8.3：文件读写 + shell） ----------

def search_files(pattern: str) -> str:
    hits = [p for p in FS if pattern in p or pattern in FS[p]]
    return f"匹配到: {hits}" if hits else f"未匹配 '{pattern}'"


def read_file(path: str) -> str:
    if path not in FS:
        return f"TOOL_ERROR: 文件不存在 {path}"
    return FS[path]


def write_file(path: str, content: str) -> str:
    # 真实环境这里应写临时工作区 + git 跟踪；demo 写入内存 FS
    FS[path] = content
    return f"已写入 {path}（{len(content)} 字符）"


def run_shell(cmd: str) -> str:
    # shell 执行的输出必须截断，避免长输出撑爆上下文（Part 8.3）
    if "test" in cmd or "pytest" in cmd:
        ok = "return" in FS.get("src/auth.py", "")
        raw = f"test_auth.py::test_login PASSED\nauth.login 返回 user 对象：{ok}"
    else:
        raw = f"$ {cmd}\n(executed ok)"
    MAX = 500
    return raw if len(raw) <= MAX else raw[:MAX] + "...[已截断]"


TOOLS = [
    Tool("search_files", "在代码库中按关键词搜索文件或内容",
         {"type": "object",
          "properties": {"pattern": {"type": "string", "description": "搜索关键词"}},
          "required": ["pattern"]}, search_files),
    Tool("read_file", "读取文件完整内容",
         {"type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]}, read_file),
    Tool("write_file", "写入或修改文件内容（沙箱，不写真实磁盘）",
         {"type": "object",
          "properties": {"path": {"type": "string"},
                         "content": {"type": "string", "description": "完整新内容"}},
          "required": ["path", "content"]}, write_file),
    Tool("run_shell", "执行 shell 命令（如跑测试），输出截断到 500 字",
         {"type": "object",
          "properties": {"cmd": {"type": "string"}},
          "required": ["cmd"]}, run_shell),
]

# 上下文工程层（Part 8.4）：这套 system prompt 决定了 agent 的"行为宪法"
SYSTEM = ("你是一个编程 agent。修复 bug 的标准动作链是："
          "search 定位文件 -> read 读源码 -> 定位根因 -> write 修复 -> run 跑测试验证。"
          "每一步只做一件事，工具结果会回流给你。")


# ---------- mock 剧本：端到端改 bug（看上一步工具结果决定下一步） ----------

def responder(messages, tools, step):
    # 关键：用上一步"调用了哪个工具"(last.name) 精确决定下一步，
    # 而不是去猜工具返回的字符串——那是 mock 剧本最常见的坑
    # （比如 write_file 的返回串里含 "auth.py"，会被误判成搜索结果）。
    last = messages[-1]
    if last.role == "user":
        # 第 1 步：用户报 issue，先搜索定位
        return tool_resp([("search_files", {"pattern": "login"})])
    if last.role == "tool":
        name = last.name
        if name == "search_files":
            # 搜索命中文件 -> 读取源码
            return tool_resp([("read_file", {"path": "src/auth.py"})])
        if name == "read_file":
            # 读到源码、发现 bug（缺 return）-> 写入修复
            return tool_resp([("write_file",
                               {"path": "src/auth.py", "content": FIXED_AUTH})])
        if name == "write_file":
            # 修复已落地 -> 跑测试验证
            return tool_resp([("run_shell", {"cmd": "pytest src/test_auth.py"})])
        if name == "run_shell":
            # 测试通过 -> 给出总结（纯文本，循环终止）
            return text_resp("已修复 login 的 bug（补上缺失的 return user），"
                             "测试 test_login 通过。可提交 PR。")
    return text_resp("任务完成。")


def main():
    banner("Lab06 · 迷你 Claude Code：端到端改一个 bug")
    issue = "修复 issue：login 函数没有 return，调用方拿到 None 导致崩溃"
    print(f"[user] {issue}\n")

    # 模型适配层（Part 6 模型适配）：mock 顶上，真实环境换 RealLLM 即可
    llm = get_llm("mock", responder=responder)

    # Agent Loop 层（Part 1.3 / 8.2）：就是那个 observe->think->act 循环
    out = run_loop(llm, TOOLS, SYSTEM, issue, max_steps=10, on_step=print_step)

    print("\n=== 最终回答 ===")
    print(out["final"])
    print(f"\n（共 {len(out['trajectory'])} 条轨迹记录）")

    # 上下文管理演示（Part 8.4）：保留"关键事件"，丢弃冗余中间思考
    print("\n--- 上下文管理：本回合保留的关键事件 ---")
    kept = [r for r in out["trajectory"]
            if r.get("tool_calls") or r.get("tool_result")]
    for r in kept:
        if r.get("tool_calls"):
            print(f"  · 动作: {r['tool_calls']}")
        elif r.get("tool_result"):
            print(f"  · 结果: {r['tool_result'][:70]}...")


if __name__ == "__main__":
    main()
