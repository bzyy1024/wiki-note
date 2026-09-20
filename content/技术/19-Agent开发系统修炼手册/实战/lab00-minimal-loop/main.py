"""
lab00 — 最简 Agent Loop

墨叔：这是所有实战的"hello world"。一个 agent 的最小骨架，就三样东西：
  1. 一个会"想"的模型（这里用 mock 顶上，没 key 也能跑）
  2. 一个会"干"的工具（get_weather，真实环境该调天气 API）
  3. 一个把两者串起来的循环（common/runner.py 的 run_loop）

跑法（默认 mock，零依赖零 key）：
    python main.py
想接真实模型：
    export OPENAI_API_KEY=sk-xxx
    AGENT_MODE=real python main.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common.llm import get_llm, scripted, text_resp, tool_resp, Message
from common.tools import Tool
from common.runner import run_loop


# ---------- 工具：真实环境这里该调天气 API，演示用 stub ----------

def get_weather(city: str) -> str:
    # stub：把这里换成 requests.get("https://api.weather.com/...") 即可
    fake_db = {"北京": "晴，22℃", "上海": "多云，19℃", "深圳": "雷阵雨，28℃"}
    return fake_db.get(city, f"{city} 天气未知")


TOOLS = [
    Tool(
        name="get_weather",
        description="查询指定城市的当前天气",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名，如 北京"}},
            "required": ["city"],
        },
        fn=get_weather,
    ),
]


# ---------- mock 剧本：把"先调工具、再总结"演出来 ----------
# 第 1 步：模型说"我先查一下北京天气"，要求调 get_weather
# 第 2 步：工具结果已回到上下文，模型给出总结（不再调工具 -> 循环结束）

def mock_responder(messages, tools, step):
    if step == 1:
        return tool_resp([("get_weather", {"city": "北京"})])
    return text_resp("北京今天天气晴朗，22℃，适合出门。")


SYSTEM = "你是一个简洁的天气助手。需要实时数据时，调用 get_weather 工具查询，再回答用户。"


def print_step(record):
    """每步回调：把循环轨迹打印出来，让你看见 agent 的"心跳"。"""
    if record.get("tool_calls"):
        for name, args in record["tool_calls"]:
            print(f"  [think] 模型要求调用工具: {name}({args})")
    elif record.get("tool_result"):
        print(f"  [act]   工具结果: {record['tool_result']}")
    elif record.get("content"):
        print(f"  [think] 模型说: {record['content']}")


def main():
    mode = os.environ.get("AGENT_MODE", "mock")
    print(f"=== lab00 最简 Agent Loop（mode={mode}）===")

    if mode == "mock":
        llm = get_llm("mock", responder=mock_responder)
    else:
        llm = get_llm("real", model=os.environ.get("AGENT_MODEL", "gpt-4o-mini"))

    user_input = "北京今天天气怎么样？"
    print(f"[user] {user_input}\n")

    out = run_loop(llm, TOOLS, SYSTEM, user_input, on_step=print_step)

    print("\n=== 最终回答 ===")
    print(out["final"])
    print(f"\n（共 {len(out['trajectory'])} 条轨迹记录）")


if __name__ == "__main__":
    main()
