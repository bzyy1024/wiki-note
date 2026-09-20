# Agent 开发实战手册 · 从最简循环到迷你 Claude Code

> 墨叔：老哥，理论那 11 个 md 是"为什么"，这盒实战是"怎么动手"。从 lab00 跑通第一个循环，到 lab06 造出能改 bug 的迷你 Claude Code，从简单到复杂，一层层把理论焊成能跑的代码。每个 lab 默认 **零依赖、零 API key、离线可跑**——先跑起来看结构，再决定要不要接真模型。

---

## 环境要求

- Python 3.10+（只用标准库，不装任何第三方包）
- 操作系统无所谓，Windows / macOS / Linux 都行

## 怎么跑

进到某个 lab 目录直接跑：

```bash
cd 实战/lab00-minimal-loop
python main.py          # 默认 mock 模式，离线即可看完整循环
```

想接真实大模型（可选）：

```bash
export OPENAI_API_KEY=sk-xxx        # lab00 / lab01 支持 AGENT_MODE=real
AGENT_MODE=real python main.py
```

> 注意：目前 lab00 / lab01 的 `main.py` 内置了 `AGENT_MODE` 切换；其余 lab 为了把机制演清楚，mock 剧本是和该 lab 知识点绑定的，跑真实模型需要你按 README 里的接口自己替换 responder。这本身就是个好练习。

## mock 是怎么做到离线可跑的

关键在 `common/llm.py` 的 `LLM` 适配层：

```
你的循环 (runner.run_loop)
        │  chat(messages, tools)
        ▼
   BaseLLM 接口  ◄── 同一套调用方式，底下可换
    ├── MockLLM   ：按你写的 responder 脚本返回（不需要网络/key）
    └── RealLLM   ：调真实 OpenAI 兼容 API（填了 key 才用）
```

写 lab 时你只关心"循环逻辑"，换模型只是换一个适配器，业务代码一行不用改——这跟你在 Go 里用 interface 屏蔽不同数据库驱动是一个道理。**mock 不是假货，是确定性的替身**：它让你在没有 key、没有网络时，也能完整观察 agent 的"心跳"（observe→think→act）和每一步轨迹。

## 目录与难度阶梯

```
实战/
├── 00-README.md          ← 你正在看的总入口
├── common/               ← 所有 lab 共用的地基（llm 适配 / 工具 / 循环 / 工具函数）
│   ├── llm.py            LLM 适配层：MockLLM + RealLLM，统一 chat 接口
│   ├── tools.py          Tool 基类与注册
│   ├── runner.py         核心 Agent Loop（observe→think→act）
│   └── util.py           各 lab 共用的轨迹打印等小工具
├── lab00-minimal-loop/   最简 Agent Loop（地基：循环 + 一个工具）
├── lab01-tools/          Function Calling + 错误处理 + 安全边界
├── lab02-planning/       Plan-and-Execute + Critic 反思循环
├── lab03-memory/         RAG 检索 + 记忆分层（user / project）
├── lab04-engineering/    流式 / checkpoint / 可观测 / HITL 护栏
├── lab05-multiagent/     Orchestrator-Worker 多智能体
├── lab06-mini-claude/    Capstone：迷你 Claude Code 端到端改 bug
└── lab07-eval/           Agent 评测：offline eval 跑通过率
```

## 与理论教程（桌面 11 个 md）的对应

| 实战 lab | 对应理论 Part | 练什么 |
|---|---|---|
| lab00 | Part 1 心智模型 | 把"Agent=大厨+递纸条的人"落成代码 |
| lab01 | Part 2 工具机制 | schema / 错误免疫系统 / 安全边界 |
| lab02 | Part 3 规划与分解 | 先想后做、Critic 自检 |
| lab03 | Part 4 记忆 | RAG 不是银弹、记忆分层 |
| lab04 | Part 5 工程化 | 流式 / 可恢复 / 可观测 / 护栏 |
| lab05 | Part 7 多智能体与编排 | Orchestrator-Worker |
| lab06 | Part 8 迷你 Claude Code 蓝图 | 把蓝图落成能改 bug 的骨架 |
| lab07 | Part 9 进阶与避坑 | 用 eval 度量 agent 变好没 |

> Part 6（Claude Code / Codex 架构剖析）是纯架构拆解，没有单独 lab，但 lab06 的 `main.py` 注释里标了它和 Part 6 各层的落点，可以对照着看。

## 学习路线建议

1. **顺序跑**：lab00 → lab07，前面是后面的词汇表。
2. **先 mock 后真实**：每个 lab 先把 mock 模式跑通、看懂轨迹，再考虑接真模型。
3. **改起来才算会**：每跑完一个 lab，试着：(a) 给它加一个你自己的工具；(b) 改 scripted 剧本让 agent 走一条不同路径；(c) 把 mock 换成 RealLLM 跑一遍。

## 几个动手改造的点子

- 给 lab01 的 `calc` 加个 `career` 工具，看看模型会不会选错（呼应 2.2 schema 设计）。
- 在 lab02 里把 Critic 从"确定性函数"换成"让模型自评"，对比两种风格。
- 把 lab06 的内存文件系统（FS 字典）换成真实目录 + git 工作区，加上"提交前 diff 预审"（呼应 Part 8.5）。
- 在 lab07 里加"轨迹评估"指标：统计每个任务走了几步工具调用、有没有走弯路。

---

一句话：**理论给你地图，实战给你腿。先跑起来，再改起来。**
