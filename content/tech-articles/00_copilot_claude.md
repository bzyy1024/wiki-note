


# GitHub Copilot 与 Claude Code 集成指南

## 概述

本文介绍如何将 GitHub Copilot 的 API 接入 Claude Code，并安装 Superpowers 插件来增强 AI 辅助编程的工作流。

---

## 一、安装 Claude Code

Claude Code 是 Anthropic 官方的终端 AI 编程工具。

### 系统要求

- macOS / Linux / Windows（WSL2）
- Node.js 18+（npm 方式安装时需要）

### 安装方式

**macOS / Linux（推荐）**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Homebrew（macOS / Linux）**

```bash
brew install --cask claude-code
```

**Windows（推荐）**

```powershell
irm https://claude.ai/install.ps1 | iex
```

**WinGet（Windows）**

```powershell
winget install Anthropic.ClaudeCode
```


**Npm**

```
npm install -g @anthropic-ai/claude-code
```

安装完成后，在任意项目目录运行 `claude` 即可启动。

---

## 二、登录与鉴权

首次运行 `claude` 时会自动打开浏览器进行登录。支持以下几种方式：

| 方式 | 说明 |
|------|------|
| Claude.ai 账号 | 适合个人 Pro/Max 订阅用户 |
| Claude Console API Key | 适合通过 Console 账单的 API 调用 |
| 云厂商（Bedrock/Vertex/Foundry） | 企业用户通过环境变量配置 |

---

## 三、接入 GitHub Copilot API

GitHub Copilot 提供了一个兼容 OpenAI 格式的 API（`https://api.githubcopilot.com`）。Claude Code 支持通过环境变量将请求路由到自定义端点，需要搭配一个将 Anthropic API 格式转换为 OpenAI 格式的网关。

npx copilot-api@latest start

### 3.1 获取 Copilot Token

确保已安装 GitHub CLI（`gh`）并完成 Copilot 授权登录：

```bash
# 安装 GitHub CLI
# macOS
brew install gh

# 登录 GitHub 并授权 Copilot
gh auth login --scopes "copilot"

# 获取 token
gh auth token
```

### 3.2 配置环境变量

将以下变量加入 shell 配置文件（`~/.bashrc` 或 `~/.zshrc`）：

```bash
# 指向支持 Copilot API 的代理网关
export ANTHROPIC_BASE_URL=https://<你的代理地址>

# 使用 Copilot token 作为鉴权凭据
export ANTHROPIC_AUTH_TOKEN=$(gh auth token)
```

> **说明**：GitHub Copilot API 使用 OpenAI 兼容格式，而 Claude Code 使用 Anthropic 格式。二者之间需要一个格式转换代理（可自建或使用第三方 LLM Gateway）。如果不使用代理，可跳过此步骤，直接用 Anthropic API Key 登录即可。

### 3.3 通过 Claude Code 配置验证

启动后运行 `/status` 查看当前鉴权方式是否生效：

```
/status
```

---

## 四、安装 Superpowers 插件

[Superpowers](https://github.com/obra/superpowers) 是专为 Claude Code 设计的工作流增强插件，提供 TDD、代码审查、任务规划等 20+ 技能。

### 4.1 方式一：通过官方 Marketplace 安装（推荐）

在 Claude Code 内运行：

```
/plugin install superpowers@claude-plugins-official
```

### 4.2 方式二：通过社区 Marketplace 安装

先注册 Marketplace，再安装插件：

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

### 4.3 验证安装

新建对话，尝试让 Claude 规划一个功能（如 "帮我规划这个功能的实现"），如果自动触发了 `brainstorming` 或 `writing-plans` 技能，说明安装成功。

### 4.4 常用技能

| 技能 | 触发场景 |
|------|----------|
| `brainstorming` | 开始编写代码前，精炼需求 |
| `writing-plans` | 设计确认后，拆分实现步骤 |
| `test-driven-development` | 实现阶段，强制 RED→GREEN→REFACTOR |
| `systematic-debugging` | 遇到 bug，4阶段根因分析 |
| `requesting-code-review` | 任务完成后，代码审查 |

### 4.5 更新插件

```
/plugin update superpowers
```

---

## 五、参考资料

- Claude Code 官方文档：https://code.claude.com/docs
- Superpowers 仓库：https://github.com/obra/superpowers
- Superpowers Marketplace：https://github.com/obra/superpowers-marketplace
- GitHub CLI 文档：https://cli.github.com/manual/



