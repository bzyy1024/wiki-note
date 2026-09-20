"""
common/llm.py — LLM 适配层（模型无关）

墨叔：这一层是 agent 和"模型"之间的翻译官。无论后面接的是真实大模型，
还是我们为了离线演示写的 mock，对上层（runner、各个 lab）来说，接口都长一样：

    给一组对话消息 + 可选的工具清单  ->  拿回一个回复
    （回复可能是纯文字，也可能是"指令你去调某个工具"）

这样设计的好处：写 lab 时你只关心"循环逻辑"，换模型只是换一个适配器，
不用改业务代码。这跟你在 Go 里用 interface 屏蔽不同数据库驱动是一个道理——
面向接口编程，底层可替换。
"""
from __future__ import annotations

import os
import json
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# ---------- 统一的消息 / 回复结构（与具体模型无关） ----------

@dataclass
class Message:
    """一条对话消息。role: system/user/assistant/tool。"""
    role: str
    content: str
    tool_calls: list = field(default_factory=list)   # 仅 assistant 使用
    tool_call_id: Optional[str] = None                # 仅 tool 消息使用
    name: Optional[str] = None                        # tool 消息对应的工具名

    def to_dict(self) -> dict:
        """转成 OpenAI 兼容的 dict（真实 API 需要这个格式）。"""
        d = {"role": self.role, "content": self.content or ""}
        if self.role == "assistant" and self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name,
                              "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
                for tc in self.tool_calls
            ]
        if self.role == "tool":
            d["tool_call_id"] = self.tool_call_id
            d["name"] = self.name
        return d


@dataclass
class ToolCall:
    """模型要求调用一个工具：工具名 + 参数。"""
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    """模型的一次回复。"""
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)


def text_resp(content: str) -> LLMResponse:
    """构造一个纯文本回复（不调工具）。"""
    return LLMResponse(content=content)


def tool_resp(calls) -> LLMResponse:
    """
    构造一个"要求调工具"的回复。
    calls: list of (name, arguments_dict)，例如 [("calc", {"a": 1, "b": 2})]
    """
    tcs = [ToolCall(id=f"call_{i}", name=n, arguments=a)
           for i, (n, a) in enumerate(calls)]
    return LLMResponse(content="", tool_calls=tcs)


# ---------- 适配器基类 ----------

class BaseLLM:
    def chat(self, messages: List[Message], tools=None) -> LLMResponse:
        raise NotImplementedError


class MockLLM(BaseLLM):
    """
    离线 mock：不联网、不需要 API key。行为完全由传入的 responder 决定。

    responder 签名：
        def responder(messages: List[Message], tools, step: int) -> LLMResponse
    你可以根据对话历史（messages）和轮次（step）返回不同回复，
    从而把"先想、再调工具、最后总结"的多步流程完整演出来。
    """

    def __init__(self, responder: Callable):
        self.responder = responder
        self.step = 0

    def chat(self, messages: List[Message], tools=None) -> LLMResponse:
        self.step += 1
        return self.responder(messages, tools, self.step)


class RealLLM(BaseLLM):
    """
    真实大模型（OpenAI 兼容协议：OpenAI / DeepSeek / 本地 vLLM 等都能用）。
    需要环境变量 OPENAI_API_KEY。没填就直接报错，提醒你切回 mock。

    注意：只用标准库 urllib，不依赖任何第三方包，保证"克隆即跑"。
    """

    def __init__(self, model: str = "gpt-4o-mini",
                 api_key: Optional[str] = None,
                 base_url: str = "https://api.openai.com/v1"):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")
        if not self.api_key:
            raise RuntimeError(
                "RealLLM 需要 OPENAI_API_KEY 环境变量。\n"
                "先 export OPENAI_API_KEY=sk-xxx，或把 get_llm 的 mode 设成 'mock'。"
            )

    def chat(self, messages: List[Message], tools=None) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
        }
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t.name,
                              "description": t.description,
                              "parameters": t.parameters}}
                for t in tools
            ]
            payload["tool_choice"] = "auto"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        msg = obj["choices"][0]["message"]
        content = msg.get("content") or ""
        tcs = []
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            try:
                args = json.loads(fn["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tcs.append(ToolCall(id=tc["id"], name=fn["name"], arguments=args))
        return LLMResponse(content=content, tool_calls=tcs)


# ---------- 便利工厂 ----------

def get_llm(mode: str = "mock", responder=None, **kwargs) -> BaseLLM:
    """
    统一入口：
      mode="mock" -> MockLLM(responder)，responder 必传
      mode="real" -> RealLLM(**kwargs)
    """
    if mode == "mock":
        if responder is None:
            raise ValueError("mock 模式必须提供 responder 函数")
        return MockLLM(responder)
    if mode == "real":
        return RealLLM(**kwargs)
    raise ValueError(f"未知 mode: {mode}")


def scripted(script):
    """
    把一串"预设回复"变成 responder，让 mock 写起来最简单。

    script: list，每个元素可以是：
      - 一个 LLMResponse（直接返回）
      - 一个 (content, calls) 元组，content 是文字、calls 是 [(工具名, 参数)]
    按顺序每次 chat 返回下一个；用尽后一直返回最后一个（避免死循环）。

    例：
      scripted([
        ("我先算一下", [("calc", {"a": 1, "b": 2})]),   # 第1步：要求调 calc
        ("结果是 3", None),                             # 第2步：给最终答案
      ])
    """
    prepared = []
    for item in script:
        if isinstance(item, LLMResponse):
            prepared.append(item)
        else:
            content, calls = item
            prepared.append(tool_resp(calls) if calls else text_resp(content))

    def responder(messages, tools, step):
        idx = min(step - 1, len(prepared) - 1)
        return prepared[idx]

    return responder
