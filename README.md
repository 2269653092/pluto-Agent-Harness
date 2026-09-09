<div align="center">

# Pluto

**Build agents that remember, continue, and learn.**

一个面向长期工作、在本地持续运行的 AI Agent Harness。

[![CI](https://github.com/Kong-lh-rgb/pluto/actions/workflows/ci.yml/badge.svg)](https://github.com/Kong-lh-rgb/pluto/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Desktop](https://img.shields.io/badge/Desktop-Electron-47848F?logo=electron&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)

[演示](#demo) · [核心能力](#what-pluto-can-do) · [架构](#how-it-fits-together) · [快速开始](#quick-start) · [评测](#evaluation)

</div>

Pluto 是一个面向长期工作的本地 AI Agent Harness。它不只完成当前对话，还会管理
长上下文、跟踪复杂任务、恢复中断 Run、使用本地与 MCP 工具，并从真实完成的工作中
逐步形成可复用的记忆与 Skill。

当前项目由 Python Host、Electron Desktop 和 Windows 原生 Computer Runtime 组成，
模型层通过统一 Adapter 接入 OpenAI、Qwen、DeepSeek 与 Anthropic。

> 当前阶段为本地开发版本，接口、数据格式和交互仍可能调整。
> 运行环境为 Windows（API Key 存 Windows 凭据管理器，Computer Runtime
> 直接调用 Win32）。

## What Pluto Can Do

- **Multi-Provider Models** — 统一适配 OpenAI、Qwen、DeepSeek 和 Anthropic API。
- **Hierarchical Agents** — Planner 主图负责判断、规划和最终汇总；简单且边界清晰的子任务通过标准载荷下发给最小权限 Worker 子图。
- **Tool System** — 本地文件、Shell、网页搜索、时间等工具共享注册、超时、权限和审计边界；Shell 默认在 workspace 沙箱中执行。
- **MCP Extensions** — 通过 Desktop 导入和管理外部 stdio MCP Server；第三方进程使用白名单环境并在 Windows 受限后端中隔离。
- **Memory** — Core Memory 常驻，Ordinary Memory 按索引由模型主动读取，并在 Run 后反思更新。
- **Task / Plan Mode** — 一个整体目标对应一个 Task，使用 Steps 跟踪复杂工作的真实进度。
- **Skill & Skill Learning** — 按需激活 Skill，并从多个 Completed Task 的 Trace 中提炼候选经验。
- **Context Management** — 每轮整理工具结果，超过预算后滚动摘要，同时保留当前目标和关键状态。
- **Run / Recovery** — 持久化 Run 生命周期，通过 Checkpoint 从中断边界创建恢复 Run。
- **Trace & Usage** — 记录模型、工具、审批、压缩和 Post-Run 事件，并拆分缓存与可计费用量。
- **Automation** — 支持 once、interval 和 cron，将定时输入送入正常 Conversation/Run 链路。
- **Async Approval** — 高风险工具可后台等待用户审批，Desktop 浮窗负责继续或拒绝执行。
- **Computer Runtime (Windows)** — Win32 原生实现提供窗口枚举、截图、坐标/元素点击与文本输入，无需系统授权弹窗。
- **Artifacts** — 将 Run 生成的文件或链接作为可追踪交付物发布到 Desktop。
- **Desktop** — 提供聊天、实时执行过程、Task、Memory、Run、Trace、Automation、Approval 和扩展管理。

## How It Fits Together

```text
Desktop / CLI / Automation
           ↓
ConversationService
           ↓
       RunManager
           ↓
                     AgentRuntime
                          ↓
                 Planner Agent 主图
                 ↙              ↘
        复杂任务自行处理       delegate_to_worker
              ↓                     ↓
Context + 完整 ToolRegistry    Worker Agent 子图
              ↓                     ↓
       Planner Model Adapter    只读工具白名单
                 ↘              ↙
                  Planner 验收与汇总
                          ↓
       Permission → Executor → Hooks → Local / MCP / Computer
                                      ↓
                          Sandbox Supervisor (Shell / MCP)
           ↓
Trace · Checkpoint · Usage · Artifact

Post-Run
  ├─ Memory Reflection / Maintenance
  └─ Task-backed Skill Learning
```

Desktop 与 Host 的正常业务链路是：

```text
Desktop
  ↓
WS /rpc (JSON-RPC)
  ↓
Pluto Host
  ↓
ConversationService / RunManager / AgentRuntime
```

`GET /health`、Computer screenshot 和 Artifact content 只承担本地 transport；正常业务
通过 `WS /rpc` 完成。Host 默认只接受 loopback 客户端。

## Core Concepts

| 概念 | 职责 |
| --- | --- |
| Conversation | 保存用户与 Agent 的完整原始消息历史 |
| Planner | 主管 Agent；判断难度、规划复杂任务、下发简单子任务并验收汇总 |
| Worker | 工人 Agent；只执行标准 `task_payload`，没有任务规划和再次委派权限 |
| Context | 为当前模型请求整理预算、工具结果和滚动摘要 |
| Task | 记录当前长期目标、Steps 和进度 |
| Memory | 保存跨会话仍值得知道的事实、偏好和决定 |
| Skill | 保存以后处理同类任务时可复用的方法 |
| Run | 表示一次 Agent 执行的完整生命周期 |
| Trace | 记录一次 Run 实际发生了什么 |
| Checkpoint | 保存中断后的可恢复边界 |
| Artifact | 表示一次 Run 可交付的文件或链接 |
| Automation | 描述未来何时向 Conversation 投递新输入 |

## Quick Start

### Requirements

- Python 3.12+
- Node.js 22+
- Windows 10/11；Computer Runtime 直接调用 Win32，无需额外系统授权

### 1. Clone and install Backend

Windows：

```powershell
git clone https://github.com/Kong-lh-rgb/pluto.git
cd pluto

python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
copy backend/.env.example backend/.env
```

Planner 与 Worker 可以在 `backend/.env` 中独立配置 Provider、模型、API Key 和
接口地址；未填写角色配置时回退到主模型配置。Worker 只会看到
`get_current_time`、`list_files`、`read_file`、`web_search` 四个基础只读工具，
不会获得写文件、Shell、Computer、Task、MCP 或再次委派权限。

```env
AGENT_HIERARCHY_ENABLED=true
PLANNER_PROVIDER=deepseek
PLANNER_MODEL=your-planner-model
PLANNER_API_KEY=your-planner-key
PLANNER_BASE_URL=https://api.deepseek.com/
WORKER_PROVIDER=deepseek
WORKER_MODEL=your-worker-model
WORKER_API_KEY=your-worker-key
WORKER_BASE_URL=https://api.deepseek.com/
```

真实 API Key 只写入本地 `backend/.env`，不要提交到 Git。

### 2. Start with CLI

Windows：

```powershell
cd backend
.venv/Scripts/python -m app --setup
.venv/Scripts/python -m app
```

CLI 可用于快速验证模型、工具、会话恢复、Memory、MCP、Run 和 Trace。
已经完成设置时可以跳过第一条命令；旧入口 `.venv/Scripts/python -m app.models.chat`
仍然兼容。

### 3. Start Pluto Host and Desktop

终端 1（Windows 用 `.venv/Scripts/python`）：

```bash
cd backend
.venv/Scripts/python -m app.server
```

终端 2：

```bash
cd desktop
npm install
npm run electron:dev
```

纯浏览器 Renderer 调试可以使用 `npm run dev`，完整桌面能力需要 Electron。

## Extensions

### MCP

Desktop 的“设置 → 扩展能力”支持粘贴 GitHub 地址或外部 `mcpServers` JSON，先展示解析
结果和即将执行的命令，再由用户确认安装。MCP 工具注册后仍会经过 Pluto 的权限、执行、
Hook 和 Trace 链路；MCP 子进程默认只能读写 workspace，Host 环境变量使用白名单传递。
可在扩展配置中关闭网络或收紧文件权限，显式选择宿主机执行会显示为危险模式。

Windows 侧使用受限后端（WindowsRestrictedBackend）：进程树收束、环境变量净化、
网络通过代理环境变量尽力限制；域名白名单暂不支持（拒绝弱化策略而非静默降级）。
容器后端和域名级网络代理仍属于后续能力。设计与边界见 [Sandbox](docs/sandbox.md)。

### Skills

Skill 可以由用户导入，也可以由 Skill Learning 从多个已完成 Task 的真实 Trace 中生成
Candidate。学习产生的 Candidate 不会绕过人工确认直接成为正式 Skill。


## Development Checks

Backend：

```powershell
cd backend
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m compileall -q app tests
```

Desktop：

```bash
cd desktop
npm ci
npm test
npm run typecheck
npm run build
```

GitHub Actions 会运行以上 Backend 和 Desktop 基线。

## Repository Layout

```text
agent/
├── backend/                         Python Harness、Host、CLI 与测试
│   ├── app/
│   │   ├── agent/                   AgentRuntime 与事件
│   │   ├── context/                 上下文构建与压缩
│   │   ├── tools/                   本地工具、权限、Executor 与 Hooks
│   │   ├── memory/                  Core / Ordinary Memory
│   │   ├── task/                    Task 与 Plan Mode
│   │   ├── skills/                  Skill Store 与运行时激活
│   │   ├── skill_learning/          Trace-backed Skill Learning
│   │   ├── run/                     Run 生命周期与 Recovery
│   │   ├── checkpoint/              恢复边界
│   │   ├── automation/              Automation 领域模型
│   │   ├── scheduler/               定时调度
│   │   ├── computer/                Windows 原生 Computer Runtime
│   │   ├── sandbox/                 Windows 受限沙箱策略与平台后端
│   │   ├── platform.py              Windows Shell、环境、文件锁与平台能力
│   │   ├── mcp/                     MCP Client
│   │   └── server/                  Pluto Host 与 WS /rpc
│   └── tests/                        离线测试、E2E 与 Eval
├── desktop/                          Electron + React + TypeScript + Vite
├── workspace/                        Agent 被允许操作的本地工作区
└── docs/                             设计、学习记录与评测报告说明
```

## Current Boundaries

- Pluto 目前以本地单用户环境为目标，不是公网多租户服务；
- Computer Runtime 仅支持 Windows；
- MCP 当前主要接入 stdio Server；
- Skill Learning 生成 Candidate，不自动绕过人工确认；
- 完整 Live Eval 成本较高，日常开发默认运行离线测试，发布前才运行完整 Regression。
