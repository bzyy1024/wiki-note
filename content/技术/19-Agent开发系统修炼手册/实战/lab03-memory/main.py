"""
lab03 — 记忆与 RAG（对应 Part 4）

墨叔：前面两节把"循环"和"工具"扒明白了。这一节聊 agent 迟早摔跟头的话题——记忆。
本 lab 用零依赖、零 API key 的 mock，把 Part 4 三件最反直觉的事跑给你看：
  1. RAG 检索链路：知识库 + retrieve(query) 关键词重叠打分 -> 拼进上下文 -> 回答
  2. RAG 不是银弹：检索到"过时/无关"资料会污染上下文，让模型一本正经地答错（再演示修正）
  3. 记忆分层：user-level（跨项目偏好）与 project-level（项目约定）两层，agent 先 recall 再行动

五个 demo：
  Demo A  RAG 基础链路      —— 检索 -> 拼接 -> 回答（正确）
  Demo B  RAG 噪声污染      —— 检索召回一条"过时资料"，模型被带偏，答错
  Demo C  RAG 防污染修正    —— 检索层加"新鲜度过滤"丢掉过时资料，答回正确
  Demo D  记忆分层·先 recall —— agent 先读 project 约定（禁用 SQLite）再决策
  Demo E  记忆写入 + 持久化  —— remember 写新约定，save/load 证明能跨会话找回

跑法（默认 mock，零依赖零 key）：
    python main.py
想接真实模型：
    export OPENAI_API_KEY=sk-xxx
    AGENT_MODE=real python main.py
"""
import os
import sys
import re
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common.llm import get_llm, scripted, text_resp, tool_resp, LLMResponse, Message, ToolCall
from common.tools import Tool
from common.runner import run_loop
from common.util import print_step, banner


# ======================================================================
# 一、极简知识库 + 检索（RAG 的"检索"这一步，不依赖任何外部库）
# ======================================================================
# 墨叔：RAG 的本质就是"检索资料拼进提示再生成"。这里用纯标准库实现"检索"——
# 一段内存里的文本清单 + 一个按"关键词重叠"打分的 retrieve 函数（不调向量库）。
#
# 每条知识是一个 dict：text 是原文，fresh 标记是否过时。注意第 5 条是
# 一条"过时资料"——它和正确资料字面相似（都讲 SQLite/数据库），但结论相反。
# 这正是 Part 4.2 说的"检索到的东西过时，反而压过正确记忆"。

KB = [
    {"text": "注册接口的请求体需包含 username、password、email 三个字段，"
             "password 必须 bcrypt 加密后存储。", "fresh": True, "source": "接口规范 v2"},
    {"text": "本项目生产环境禁止使用 SQLite，统一使用 Postgres；"
             "数据库密码通过 DATABASE_URL 环境变量注入，禁止硬编码。", "fresh": True, "source": "架构决策"},
    {"text": "本项目采用 1Panel 进行服务器运维，部署走 Docker + Nginx。", "fresh": True, "source": "运维手册"},
    {"text": "所有对外 API 返回统一 JSON 结构，错误码用 code/message 字段。", "fresh": True, "source": "接口规范 v2"},
    # ↓↓↓ 过时资料：2023 年的旧结论，已不适用于当前项目，却是 RAG 噪声的经典来源
    {"text": "SQLite 是一款轻量嵌入式数据库，单机应用性能很好，适合小型项目快速起步。",
     "fresh": False, "source": "2023年旧文档"},
]


def _keywords(text: str) -> set:
    """
    极简分词：英文/数字按词，中文按 2-gram。
    目的只是给"关键词重叠打分"一个可比的集合，不追求语言学正确。
    """
    text = text.lower()
    en = set(re.findall(r"[a-z0-9_]+", text))
    cjk = "".join(re.findall(r"[一-鿿]", text))
    grams = set(en)
    for i in range(len(cjk) - 1):
        grams.add(cjk[i:i + 2])
    return grams


def retrieve(query: str, top_k: int = 2, filtered: bool = False) -> list:
    """
    关键词重叠打分检索（不依赖向量库）。

    filtered=True 时，先丢弃 fresh=False 的过时资料——这是 Part 4.2 讲的
    "防污染过滤"的最朴素实现：检索回来不代表能信，进窗口前先按新鲜度降级。

    返回 [(score, doc), ...]，score 是重叠词数 / 查询词数。
    """
    q = _keywords(query)
    pool = [d for d in KB if (d["fresh"] or not filtered)]  # filtered 时剔除过时资料
    scored = []
    for doc in pool:
        overlap = len(q & _keywords(doc["text"]))
        if overlap == 0:
            continue
        scored.append((overlap / max(len(q), 1), doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


def search_kb(query: str, filter_noise: bool = False) -> str:
    """
    工具函数：把检索结果拼成一段可喂回模型的文本。
    filter_noise=True 等价于 retrieve(filtered=True)——丢弃过时资料。
    """
    hits = retrieve(query, top_k=2, filtered=filter_noise)
    if not hits:
        return "（知识库未检索到相关内容）"
    lines = []
    for score, doc in hits:
        tag = "" if doc["fresh"] else " [⚠️ 过时资料]"
        lines.append(f"[相关度 {score:.2f} | {doc['source']}]{tag} {doc['text']}")
    return "知识库检索结果：\n" + "\n".join(lines)


# ======================================================================
# 二、记忆分层（user-level / project-level），带 save/load/recall
# ======================================================================
# 墨叔：长期记忆存外部。精确事实（"禁用 SQLite"）走结构化 KV，绝不走向量——
# 因为 KV 是按 key 精确取，向量是"相似度排序"容得下"第二相似"把你带偏。
# 这里用两层 dict 模拟，并提供 save/load 演示持久化（写文件）。

CURRENT_PROJECT = "agent-book"
MEMORY_FILE = os.path.join(HERE, ".lab03_memory_store.json")


class Memory:
    def __init__(self):
        self.user = {}        # user-level：跨项目，跟人走（如 语言=Go、风格=反水字数）
        self.projects = {}    # project-level：按项目名隔离（如 本项目禁用 SQLite）

    def write(self, scope: str, key: str, value, project: str = None) -> str:
        if scope == "user":
            self.user[key] = value
            return f"已写入 user 记忆: {key}={value}"
        if scope == "project":
            proj = project or CURRENT_PROJECT
            self.projects.setdefault(proj, {})[key] = value
            return f"已写入 project[{proj}] 记忆: {key}={value}"
        return "TOOL_ERROR: 未知 scope（应为 user 或 project）"

    def recall(self, scope: str, project: str = None) -> str:
        if scope == "user":
            return "user 记忆: " + json.dumps(self.user, ensure_ascii=False)
        if scope == "project":
            proj = project or CURRENT_PROJECT
            return f"project[{proj}] 记忆: " + json.dumps(
                self.projects.get(proj, {}), ensure_ascii=False)
        return "TOOL_ERROR: 未知 scope（应为 user 或 project）"

    def save(self) -> str:
        """持久化到文件（演示跨会话找回）。真实系统可换成 KV/数据库。"""
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"user": self.user, "projects": self.projects}, f,
                      ensure_ascii=False, indent=2)
        return f"记忆已保存到 {MEMORY_FILE}"

    def load(self) -> str:
        if not os.path.exists(MEMORY_FILE):
            return "（无已保存的记忆文件）"
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.user = data.get("user", {})
        self.projects = data.get("projects", {})
        return "记忆已从文件加载"


# 全局记忆实例，预置一条 project 约定（正是 Demo D 要召回的）
memory = Memory()
memory.write("user", "lang", "Go")
memory.write("user", "style", "反水字数、要深度答案")
memory.write("project", "no_sqlite", True, project=CURRENT_PROJECT)
memory.write("project", "deploy", "1Panel", project=CURRENT_PROJECT)


# ======================================================================
# 三、工具定义（fn 参数名须匹配 parameters.required，run_loop 用 **args 调用）
# ======================================================================

def search_kb_tool(query: str, filter_noise: bool = False) -> str:
    return search_kb(query, filter_noise=filter_noise)


def recall_memory(scope: str, project: str = None) -> str:
    return memory.recall(scope, project=project)


def remember(scope: str, key: str, value, project: str = None) -> str:
    return memory.write(scope, key, value, project=project)


TOOLS = [
    Tool("search_kb",
         "在知识库检索相关资料，返回 top-k 片段。filter_noise=True 时丢弃过时资料。",
         {"type": "object",
          "properties": {
              "query": {"type": "string", "description": "用户的检索问题"},
              "filter_noise": {"type": "boolean",
                               "description": "是否过滤过时资料，默认 False"}},
          "required": ["query"]},
         search_kb_tool),
    Tool("recall_memory",
         "读取记忆：scope=user 读用户级偏好，scope=project 读项目约定（需 project 名）。",
         {"type": "object",
          "properties": {
              "scope": {"type": "string", "enum": ["user", "project"]},
              "project": {"type": "string", "description": "项目名，scope=project 时填"}},
          "required": ["scope"]},
         recall_memory),
    Tool("remember",
         "写入记忆：scope=user/project，key/value 为要记的内容，project 为项目名。",
         {"type": "object",
          "properties": {
              "scope": {"type": "string", "enum": ["user", "project"]},
              "key": {"type": "string"},
              "value": {},
              "project": {"type": "string", "description": "项目名，scope=project 时填"}},
          "required": ["scope", "key", "value"]},
         remember),
]

SYSTEM = ("你是一个工程助手。需要外部知识时调用 search_kb 检索；涉及用户偏好或项目约定时，"
          "先调用 recall_memory 读取对应层级的记忆，再据此行动。回答要基于检索/记忆的真实内容。")


# ======================================================================
# 四、mock 剧本（responder 看 messages 最后一条的 role 决定返回，模拟"续写机器"）
# ======================================================================

def rag_basic_responder(messages, tools, step):
    # 第 1 步：还没检索 -> 先调 search_kb
    if messages[-1].role != "tool":
        return tool_resp([("search_kb", {"query": "注册接口 请求体 字段"})])
    # 检索结果已回到上下文 -> 模型基于资料作答（这次资料是对的）
    return text_resp("根据知识库：注册接口请求体需包含 username、password、email 三个字段，"
                     "且 password 必须经过 bcrypt 加密后存储。")


def rag_noise_responder(messages, tools, step):
    # 第 1 步：检索（不过滤 -> 过时资料也召回）
    if messages[-1].role != "tool":
        return tool_resp([("search_kb", {"query": "生产环境 用什么 数据库"})])
    # 第 2 步：看到检索结果。过时资料"SQLite 性能很好"在场 -> 模型被带偏，答错
    last = messages[-1].content
    if "性能很好" in last:  # 上下文污染：模型顺着眼前最显眼的过时资料续写
        return text_resp("根据资料，本项目生产环境可以使用 SQLite（轻量、性能很好）。")
    return text_resp("根据资料，本项目禁止在生产使用 SQLite，应使用 Postgres。")


def rag_fix_responder(messages, tools, step):
    # 第 1 步：检索时带 filter_noise=True -> 检索层已丢弃过时资料
    if messages[-1].role != "tool":
        return tool_resp([("search_kb",
                           {"query": "生产环境 用什么 数据库", "filter_noise": True})])
    # 第 2 步：上下文里只剩正确的新鲜资料 -> 模型答回正确
    return text_resp("根据资料，本项目禁止在生产使用 SQLite，统一使用 Postgres。")


def memory_recall_responder(messages, tools, step):
    # 第 1 步：动手前先 recall 项目约定（"先读约定再行动"）
    if messages[-1].role != "tool":
        return tool_resp([("recall_memory",
                           {"scope": "project", "project": CURRENT_PROJECT})])
    # 第 2 步：看到"禁用 SQLite"约定 -> 据此选数据库，而不是无脑用 SQLite
    last = messages[-1].content
    if "no_sqlite" in last or "禁用" in last:
        return text_resp("已读取项目约定：禁用 SQLite。因此数据持久化改用 Postgres，"
                         "不引入 SQLite；数据库密码走 DATABASE_URL 注入。")
    return text_resp("好的，我来加数据持久化。")


# ======================================================================
# 五、运行各 demo
# ======================================================================

def run_demo(title, responder, user):
    banner(title)
    print(f"[user] {user}\n")
    llm = get_llm("mock", responder=responder)
    out = run_loop(llm, TOOLS, SYSTEM, user, on_step=print_step)
    print(f"\n  最终回答: {out['final']}")
    return out["final"]


def main():
    print("=== lab03 记忆与 RAG（mode=mock，零依赖零 key）===")

    # Demo A：RAG 基础链路——检索 -> 拼接 -> 回答
    run_demo("Demo A · RAG 基础链路（检索→回答）", rag_basic_responder,
             "注册接口的请求体需要哪些字段？怎么存密码？")

    # Demo B：RAG 噪声污染——过时资料被召回，模型被带偏答错
    wrong = run_demo("Demo B · RAG 噪声污染（被过时资料带偏，答错）", rag_noise_responder,
                     "我们生产环境用哪个数据库？")

    # Demo C：RAG 防污染修正——检索层过滤过时资料，答回正确
    run_demo("Demo C · RAG 防污染修正（过滤过时资料后答对）", rag_fix_responder,
             "我们生产环境用哪个数据库？")

    # Demo D：记忆分层——先 recall 项目约定（禁用 SQLite）再决策
    run_demo("Demo D · 记忆分层（先 recall project 约定再行动）", memory_recall_responder,
             "帮我给这个项目加个数据持久化层")

    # Demo E：记忆写入 + 持久化（save/load 跨会话找回）
    banner("Demo E · 记忆写入 + 持久化（remember → save → load）")
    llm = get_llm("mock", responder=lambda m, t, s: text_resp("已记录。"))
    # 主动写入一条新项目约定，再 save，再新建实例 load 验证找回
    memory.write("project", "api_style", "gRPC", project=CURRENT_PROJECT)
    print("  [act] 写入新约定:", memory.recall("project", CURRENT_PROJECT))
    print("  [act]", memory.save())
    fresh = Memory()
    print("  [act]", fresh.load())
    print(f"  [act] 新会话加载到的 project 约定: {fresh.recall('project', CURRENT_PROJECT)}")

    # 收口对照：B 答错、C 答对，正是"检索质量决定生成质量、检索无纠错机制"的实证
    print("\n=== 小结 ===")
    print(f"  Demo B 被污染回答: {wrong}")
    print("  → RAG 不是银弹：检索到的资料进了窗口，模型就当权威续写；")
    print("    防御=检索后加相关性/新鲜度过滤，把'候选参考'降级、不当'铁律'。")


if __name__ == "__main__":
    main()
