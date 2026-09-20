"""
lab04 — 工程化（对应教程 Part 5）

墨叔：前几个 lab 我们让 agent "能想、能动手、能记"。但那些还是实验室玩具。
这一节把玩具拧成生产级工具，从四个工程维度各写一个可运行 demo：

  1. 流式输出    —— stream_print：把最终答案逐字吐出，体现"一边想一边显示"
  2. 状态持久化  —— save_messages / load_messages + run_agent(..., messages=...) 断点续跑
  3. 可观测性    —— TraceCollector：每步记 trace（步骤/工具/耗时/ token），汇总报告
  4. 安全护栏    —— require_confirm：危险动作执行前必须过人类这关（HITL），演示拒绝/确认两分支

跑法（默认 mock，零依赖零 key）：
    python main.py

想接真实模型：
    export OPENAI_API_KEY=sk-xxx
    AGENT_MODE=real python main.py
"""
import os
import sys
import time
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common.llm import get_llm, scripted, text_resp, tool_resp, LLMResponse, Message, ToolCall
from common.tools import Tool, find_tool
from common.runner import run_loop
from common.util import print_step, banner


# ============================================================
# 维度二：状态持久化 / checkpoint（对应 Part 5.1）
#   把 agent 的"纸条" messages 落盘成 json，崩了能 load 回来续跑。
#   Message 是 dataclass，含 tool_calls（ToolCall 列表），需自定义序列化。
# ============================================================

def message_to_dict(m: Message) -> dict:
    """把一条消息序列化成纯 dict（role/content/tool_calls/tool_call_id/name）。"""
    d = {"role": m.role, "content": m.content or ""}
    if m.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in m.tool_calls
        ]
    if m.tool_call_id is not None:
        d["tool_call_id"] = m.tool_call_id
    if m.name is not None:
        d["name"] = m.name
    return d


def dict_to_message(d: dict) -> Message:
    """dict -> Message（把 tool_calls 还原成 ToolCall 对象）。"""
    tcs = [
        ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
        for tc in d.get("tool_calls", [])
    ]
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        tool_calls=tcs,
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )


def save_messages(messages: list, path: str):
    """把整张纸条 append-only 式落盘（这里直接整段覆盖写 json，足够演示）。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump([message_to_dict(m) for m in messages], f, ensure_ascii=False, indent=2)


def load_messages(path: str) -> list:
    """读回纸条：崩了也能'回忆起'自己跑到哪。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [dict_to_message(d) for d in json.load(f)]


# ============================================================
# 维度一：流式输出（对应 Part 5.2）
#   模型本就是"逐 token 生产"，把最终答案逐字 print，模拟丝滑的增量渲染。
# ============================================================

def stream_print(text: str, delay: float = 0.008):
    """把文字一个字一个字吐出来，模拟 SSE/chunked 的增量渲染。"""
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)   # 真实场景里这个延迟是网络/模型在"生产"，这里用 sleep 模拟
    print()                 # 收尾换行


# ============================================================
# 维度三：可观测性（对应 Part 5.4）
#   给每一步记一条 span，最后汇总成一条 trace 报告（类似 OTel 的瀑布图）。
# ============================================================

def est_tokens(text: str) -> int:
    """token 粗估：中英混排按 ~2 字符/token 估，纯做"量级感知"用。"""
    return max(0, len(text or "") // 2)


def est_in_tokens(messages: list) -> int:
    """估算某次调用要喂进去的"整段上下文" token 数（演示"每圈都重付一次输入钱"）。"""
    n = 0
    for m in messages:
        n += len(m.content or "")
        for tc in m.tool_calls:
            n += len(str(tc.arguments))
    return n // 2


class TraceCollector:
    """收集一次运行的全部 span，最后打印 trace 报告。"""
    def __init__(self, trace_id: str):
        self.trace_id = trace_id
        self.spans = []

    def add(self, step, kind, name, in_tok, out_tok, ms, detail=""):
        self.spans.append({
            "step": step, "kind": kind, "name": name,
            "in_tok": in_tok, "out_tok": out_tok, "ms": ms, "detail": detail,
        })

    def report(self):
        print(f"\n  📈 Trace 报告 (trace_id={self.trace_id})")
        print(f"  {'步骤':<4}{'类型':<8}{'名称':<14}{'输入tok':>8}{'输出tok':>8}{'耗时ms':>9}  摘要")
        print(f"  {'-'*70}")
        for s in self.spans:
            print(f"  {s['step']:<4}{s['kind']:<8}{s['name']:<14}"
                  f"{s['in_tok']:>8}{s['out_tok']:>8}{s['ms']:>9.1f}  {s['detail'][:24]}")
        tot_in = sum(s["in_tok"] for s in self.spans)
        tot_out = sum(s["out_tok"] for s in self.spans)
        tot_ms = sum(s["ms"] for s in self.spans)
        print(f"  {'-'*70}")
        print(f"  {'合计':<4}{'':<8}{len(self.spans):<14}{tot_in:>8}{tot_out:>8}{tot_ms:>9.1f}")
        # 点出工程真相：输入 token 被重复付费——上下文越长、圈数越多越贵
        print(f"  💡 注意：'输入tok'每圈几乎相同，说明整段上下文被反复喂给模型，")
        print(f"     这正是 Part 5.3 说的成本主引擎：圈数 × 上下文长度。")


# ============================================================
# 维度四：安全护栏 HITL（对应 Part 5.5）
#   危险工具执行前必须过人类这一关；mock 用环境变量模拟"人拒绝/人确认"。
# ============================================================

def _human_decision() -> bool:
    """mock 的人类：读 HITL_ALLOW 决定自动确认/拒绝。
    真实系统里这里会真的弹窗等你按 y/n（非阻塞、可预设策略）。"""
    return os.environ.get("HITL_ALLOW", "0") == "1"


def require_confirm(fn):
    """危险工具包装器：执行前必须先过人类确认这关。模型只有'申请权'，没有'执行权'。"""
    def wrapped(**kwargs):
        print(f"  [HITL] 模型请求执行危险操作 {fn.__name__}({kwargs})")
        if _human_decision():
            print("  [HITL] 人类确认：允许执行 ✅")
            return fn(**kwargs)
        print("  [HITL] 人类拒绝：已拦截 ⛔")
        return f"SAFETY_DENY: 人类拒绝了危险操作 {fn.__name__}，请换一个安全方案。"
    return wrapped


# ============================================================
# 通用循环封装：在 common.runner.run_loop 之上，叠加
#   - 每步 trace 记录
#   - 每步 checkpoint 落盘
#   - 支持从已有 messages 恢复续跑（断点续跑）
# ============================================================

def run_agent(llm, tools, system_prompt: str, user_input: str = None, *,
              messages: list = None, max_steps: int = 12,
              on_step=None, trace: TraceCollector = None,
              checkpoint_path: str = None, checkpoint_every: int = 1) -> dict:
    # 恢复模式：传入 messages 就接着跑；否则从 system + user 初始化
    if messages is None:
        messages = [Message("system", system_prompt),
                    Message("user", user_input)]

    final = None
    for step in range(1, max_steps + 1):
        # --- think：模型产出 ---
        t0 = time.time()
        resp = llm.chat(messages, tools)
        think_ms = (time.time() - t0) * 1000
        in_tok = est_in_tokens(messages)
        out_tok = est_tokens(resp.content)

        record = {"step": step, "content": resp.content,
                  "tool_calls": [(tc.name, tc.arguments) for tc in resp.tool_calls]}
        if on_step:
            on_step(record)
        if trace is not None:
            trace.add(step, "llm", "model", in_tok, out_tok, think_ms, resp.content[:30])

        if not resp.tool_calls:
            # 模型不再要求调工具 -> 最终回答
            final = resp.content
            break

        # 把 assistant 的"调工具意图"写回纸条（真实 API 需要这条上下文接 tool 结果）
        messages.append(Message("assistant", resp.content, tool_calls=resp.tool_calls))

        # --- act：逐个执行工具 ---
        for tc in resp.tool_calls:
            tt0 = time.time()
            tool = find_tool(tools, tc.name)
            if tool is None:
                result = f"TOOL_ERROR: 未知工具 {tc.name}"
            else:
                result = tool.run(tc.arguments)   # Tool.run 已 try/except 包异常
            tool_ms = (time.time() - tt0) * 1000
            messages.append(Message("tool", result, tool_call_id=tc.id, name=tc.name))
            if on_step:
                on_step({"step": step, "tool_result": f"{tc.name}({tc.arguments}) -> {result}"})
            if trace is not None:
                trace.add(step, "tool", tc.name,
                          est_tokens(str(tc.arguments)), est_tokens(result),
                          tool_ms, result[:30])

        # 在"成本高/不可逆"的节点打快照
        if checkpoint_path and (step % checkpoint_every == 0):
            save_messages(messages, checkpoint_path)

    if final is None:
        final = "（达到最大步数仍未给出最终回答）"
    if checkpoint_path:
        save_messages(messages, checkpoint_path)   # 末态也落盘
    return {"final": final, "messages": messages}


# ============================================================
# 工具定义（真实环境换成调 API / 执行命令；演示用 stub）
# ============================================================

def research(topic: str) -> str:
    return (f"关于『{topic}』的调研结果：Agent 工程化的核心是——状态可恢复、"
            f"输出可流式、运行可观测、动作有护栏。")


def calc(a, b):
    return a + b


def read_status() -> str:
    return "生产环境状态：所有服务正常，QPS 1200，无告警。"


@require_confirm
def deploy(target: str) -> str:
    """危险工具：发布到指定环境。被 require_confirm 包住，执行前必过人类。"""
    return f"已部署到 {target}，版本 v1.2.3 上线成功。"


TOOLS = [
    Tool("research", "调研某个主题，返回要点摘要",
         {"type": "object",
          "properties": {"topic": {"type": "string", "description": "调研主题"}},
          "required": ["topic"]}, research),
    Tool("calc", "计算两个数字相加",
         {"type": "object",
          "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
          "required": ["a", "b"]}, calc),
    Tool("read_status", "只读查看生产环境状态，无副作用",
         {"type": "object", "properties": {}}, read_status),
    Tool("deploy", "部署到指定环境（危险操作，需人类确认）",
         {"type": "object",
          "properties": {"target": {"type": "string", "description": "目标环境，如 prod"}},
          "required": ["target"]}, deploy),
]

SYSTEM = ("你是一个工程化的 Agent 助手。需要调研用 research，计算用 calc，"
          "查看状态用 read_status。deploy 是危险操作，执行前需人类确认。")


# ============================================================
# 各 demo 用的 mock 剧本（看 messages 最后一条 role 决定下一步）
# ============================================================

def _called_tools(messages):
    """从纸条里扒出模型已经调过哪些工具，用来决定下一步演什么。"""
    return [tc.name for m in messages if m.role == "assistant" for tc in m.tool_calls]


def streaming_responder(messages, tools, step):
    last = messages[-1]
    if last.role == "user":
        return tool_resp([("research", {"topic": "流式输出"})])
    if last.role == "tool":
        return text_resp("流式输出的本质，是把模型'逐 token 生产'的节奏原样外化给用户——"
                         "它不加速模型，只把等待感切碎，让你随时能打断、随时能止损。")
    return text_resp("完成。")


def checkpoint_responder(messages, tools, step):
    if "research" not in _called_tools(messages):
        return tool_resp([("research", {"topic": "断点续跑"})])
    return text_resp("基于调研：把 messages 落盘即可断点续跑——崩溃后 load 回来，"
                     "从最后一条消息继续，不用从头再来。")


def obs_responder(messages, tools, step):
    called = _called_tools(messages)
    if "research" not in called:
        return tool_resp([("research", {"topic": "可观测性"})])
    if "calc" not in called:
        return tool_resp([("calc", {"a": 3, "b": 4})])
    return text_resp("可观测性的三层：结构化日志记事实、trace 用唯一 id 串起动作树、"
                     "eval 把观测变仪表盘驱动迭代。")


def hitl_responder(messages, tools, step):
    called = _called_tools(messages)
    if "deploy" not in called:
        return tool_resp([("deploy", {"target": "prod"})])
    last = messages[-1]
    if last.role == "tool" and "SAFETY_DENY" in last.content:
        return text_resp("人类拒绝了部署。我改为只读汇报：生产环境由人工发布流程把控，"
                         "本次未做任何自动变更。")
    return text_resp("部署已获人类确认，生产环境已更新到新版本，发布完成。")


# ============================================================
# 四个 demo
# ============================================================

def demo_streaming():
    banner("维度一 · 流式输出：让答案「一边想一边显示」")
    user = "给我讲讲流式输出到底解决了什么问题？"
    print(f"[user] {user}\n")
    llm = get_llm("mock", responder=streaming_responder)
    out = run_loop(llm, TOOLS, SYSTEM, user, on_step=print_step)
    print("\n  —— 下面是'流式'渲染最终答案（逐字吐出） ——")
    stream_print(out["final"])


def demo_checkpoint():
    banner("维度二 · 状态持久化 / 断点续跑：中途崩溃也能接着干")
    ckpt = os.path.join(HERE, "checkpoint.json")
    user = "帮我调研一下断点续跑该怎么做。"

    # 第一次运行：故意只跑 1 步，模拟"进程崩了"
    print(f"[user] {user}\n")
    llm1 = get_llm("mock", responder=checkpoint_responder)
    print("  （第一跑：max_steps=1，跑到第 1 步调完 research 就'崩溃'）")
    out1 = run_agent(llm1, TOOLS, SYSTEM, user,
                     max_steps=1, on_step=print_step, checkpoint_path=ckpt)
    print(f"  ⚠️  模拟崩溃，final 未产出。已落盘 checkpoint -> {ckpt}")

    # 模拟崩溃间隔：从磁盘读回纸条
    recovered = load_messages(ckpt)
    print(f"  🔄 从 checkpoint 恢复 {len(recovered)} 条消息，续跑……\n")

    # 第二次运行：从读回的 messages 接着跑
    llm2 = get_llm("mock", responder=checkpoint_responder)
    out2 = run_agent(llm2, TOOLS, SYSTEM, user,
                     messages=recovered, on_step=print_step, checkpoint_path=ckpt)
    print(f"\n  ✅ 续跑完成，最终回答: {out2['final']}")

    # 清理演示产物
    try:
        os.remove(ckpt)
    except OSError:
        pass


def demo_observability():
    banner("维度三 · 可观测性：把一次运行变成可回放的 trace")
    user = "调研可观测性，并算一下 3+4，最后总结。"
    print(f"[user] {user}\n")
    llm = get_llm("mock", responder=obs_responder)
    trace = TraceCollector(trace_id="abc123")
    out = run_agent(llm, TOOLS, SYSTEM, user,
                    on_step=print_step, trace=trace)
    trace.report()
    print(f"\n  最终回答: {out['final']}")


def demo_hitl():
    banner("维度四 · 安全护栏 HITL：危险动作必须人类拍板")
    user = "帮我把新版本部署到生产环境 prod。"

    # 分支 A：人类拒绝
    print(f"[user] {user}\n")
    os.environ["HITL_ALLOW"] = "0"
    print("  —— 分支 A：人类拒绝 ——")
    llm_a = get_llm("mock", responder=hitl_responder)
    out_a = run_agent(llm_a, TOOLS, SYSTEM, user, on_step=print_step)
    print(f"  最终回答: {out_a['final']}\n")

    # 分支 B：人类确认
    print("  —— 分支 B：人类确认 ——")
    os.environ["HITL_ALLOW"] = "1"
    llm_b = get_llm("mock", responder=hitl_responder)
    out_b = run_agent(llm_b, TOOLS, SYSTEM, user, on_step=print_step)
    print(f"  最终回答: {out_b['final']}")


def main():
    mode = os.environ.get("AGENT_MODE", "mock")
    print(f"=== lab04 工程化（mode={mode}）===")
    if mode == "real":
        # 真实模式：用一个会"先看消息再决定"的 responder 不适用，
        # 这里退化成 scripted 也行；真实模式更推荐直接换 RealLLM。
        # 为保持 demo 可跑，real 模式仍走 mock 剧本（仅示意接口）。
        pass
    demo_streaming()
    demo_checkpoint()
    demo_observability()
    demo_hitl()
    print("\n=== lab04 全部 demo 结束 ===")


if __name__ == "__main__":
    main()
