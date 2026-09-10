# Pluto 推荐代码阅读顺序

> 目标：先建立一条能运行的主链路，再逐层理解工具、上下文、持久化和桌面能力。不要从文件数量最多的模块开始，也不要试图第一遍记住所有数据模型。

配套材料：[项目面试手册](interview-guide.md)。面试手册负责解释原理和八股，本文负责告诉你按什么顺序打开源码、每一步看什么。

## 1. 总体阅读原则

建议使用“入口 → 主链路 → 横切能力 → 扩展能力 → 测试”的顺序：

```text
配置与入口
  → Application 依赖组装
  → Conversation 输入
  → Run 生命周期
  → AgentLoop 模型/工具循环
  → 工具权限与 Planner/Worker
  → Context、Trace、Checkpoint
  → Memory、Task、Skill
  → MCP、Automation、Computer
  → Desktop 实时交互
  → 测试验证理解
```

每读一个模块只回答五个问题：

1. 它接收什么输入？
2. 它返回什么结果或产生什么副作用？
3. 它依赖谁，由谁创建？
4. 失败、取消或重启时怎样处理？
5. 对应测试在哪里？

第一遍不要逐行研究所有 Store 和 UI 样式。先能从用户输入追踪到最终答案，再补局部实现。

## 2. 第 0 阶段：了解项目边界

### 2.1 阅读文件

1. `README.md`
2. `backend/requirements.txt`
3. `backend/requirements-dev.txt`
4. `backend/pyproject.toml`
5. `desktop/package.json`
6. `.github/workflows/ci.yml`
7. `docs/interview-guide.md` 第 1～4 节

### 2.2 应该得到的结论

- 项目是 Windows 本地单用户 Agent Harness。
- 后端是 Python 异步运行时，桌面端是 Electron + React。
- 正常业务使用 WebSocket 上的 JSON-RPC；HTTP 主要承担健康检查和内容传输。
- Planner/Worker 是自研 AgentLoop 的嵌套调用，没有使用 LangGraph。
- 数据既有 SQLite，也有 Markdown/JSON 文件。

### 2.3 自测

不用看文档，能否用一分钟说明项目解决的问题、技术栈和当前限制？

## 3. 第 1 阶段：从入口看依赖如何组装

### 3.1 CLI 与 Host 入口

按顺序阅读：

1. `backend/app/__main__.py`
2. `backend/app/server/__main__.py`
3. `backend/app/server/app.py` 中的 `create_app()` 和 lifespan
4. `backend/app/application.py` 中的 `Application.__init__()`、`start()`、`runtime()`、`close()`

### 3.2 阅读重点

- CLI 和 Desktop Host 是否复用同一个 Application？
- `Application.__init__()` 为什么主要保存配置，而大量 I/O 初始化放在 `start()`？
- Store、模型 Registry、ToolRegistry、RunManager、ConversationService 在什么顺序创建？
- `close()` 为什么需要按依赖关系反向释放资源？
- 分层 Agent 开关怎样影响 Planner 与 Worker 的模型注册表？

### 3.3 建议画图

```text
Application
├─ ModelAdapterRegistry
├─ ToolRegistry / ToolExecutor
├─ ConversationService
├─ RunManager
│  └─ AgentRuntime
├─ SQLite / File Stores
├─ AutomationScheduler
├─ MCPManager
└─ PostRunProcessor
```

读完后应该能回答：“程序启动时谁创建 AgentRuntime，谁负责最终关闭模型客户端？”

## 4. 第 2 阶段：先理解统一数据协议

### 4.1 阅读文件

1. `backend/app/models/types.py`
2. `backend/app/models/config.py`
3. `backend/app/models/adapter.py`
4. `backend/app/models/registry.py`
5. `backend/app/agent/result.py`
6. `backend/app/agent/events.py`
7. `backend/app/run/models.py`

### 4.2 阅读重点

- `Message`、`ToolCall`、`ToolResult` 如何表达一次工具往返？
- `ModelRequest` 和 `ModelResponse` 如何隔离 Provider SDK 类型？
- `AgentResult` 与 `Run` 有何区别？
- Event、Trace、业务状态为什么不能混成一个对象？
- Pydantic 的 `extra="forbid"`、Field 校验和 Enum 分别解决什么问题？

暂时不要深挖每个 Provider 的流式分片。先记住：运行时只依赖统一 Adapter 接口。

## 5. 第 3 阶段：追踪一条输入的主链路

### 5.1 阅读顺序

1. `backend/app/conversation/service.py`：`dispatch()`、`_dispatch_locked()`
2. `backend/app/run/manager.py`：`start()`、`wait()`、`_execute()`
3. `backend/app/agent/runtime.py`：`run()`、`run_stream()`
4. `backend/app/agent/loop.py`：`AgentLoop.run()`
5. `backend/app/models/providers/openai_compatible.py`：`complete_stream()`
6. `backend/app/conversation/store.py`：消息怎样写回

### 5.2 带着这个调用链阅读

```text
ConversationService.dispatch
  → load history / summary
  → RunManager.start
  → asyncio.create_task(RunManager._execute)
  → AgentRuntime.run_stream
  → AgentLoop.run
  → ModelAdapter.complete_stream
  → Tool call 或 final message
  → AgentResult
  → 保存 Conversation 和 Summary
```

### 5.3 必须看懂的细节

- 同一个 Conversation 为什么要锁住完整的 load→run→save，而不是只锁数据库写入？
- RunManager 为什么既返回 run_id 又保留 `asyncio.Task`？
- 模型流式增量和最终完整 ModelResponse 如何同时存在？
- 用户取消后为什么还要为 Conversation 合成终态消息？
- Desktop 断线为什么不会自动取消 Run？

读完后，用调试器在 `ConversationService.dispatch()`、`RunManager.start()`、`AgentLoop.run()` 各放一个断点，实际发送一条消息观察调用栈。

## 6. 第 4 阶段：拆解 AgentLoop

`backend/app/agent/loop.py` 较长，不建议从第一行连续读到最后一行。按以下关注点分块阅读：

1. `AgentLoop.__init__()`：循环依赖和上限。
2. `run()` 开头：历史、系统提示、恢复证据、Task/Memory/Skill 上下文怎样进入请求。
3. 上下文准备处：`ContextManager.prepare()` 的输入。
4. 模型调用处：流式回调、usage 与预算。
5. 工具响应分支：怎样进入 `ToolRoundExecutor`。
6. 最终文本与停止原因：怎样形成 `AgentResult`。
7. 异常与 finally：临时权限、事件和资源怎样收尾。

同时打开：

- `backend/app/agent/context_session.py`
- `backend/app/agent/tool_round_executor.py`
- `backend/app/agent/runtime_helpers.py`
- `backend/app/agent/budget.py`
- `backend/app/agent/computer_guard.py`

建议为一次运行记录以下变量变化：`step`、`round_index`、`messages`、`usage`、`activated_tools`、`summary_state` 和 `stop_reason`。

## 7. 第 5 阶段：工具系统与权限

### 7.1 阅读顺序

1. `backend/app/tools/base.py`
2. `backend/app/tools/registry.py`
3. `backend/app/tools/catalog.py`
4. `backend/app/tools/executor.py`
5. `backend/app/agent/tool_round_executor.py`
6. `backend/app/tools/hooks.py`
7. `backend/app/tools/permission_hook.py`
8. `backend/app/tools/permissions/policy.py`
9. `backend/app/approval/gate.py`
10. `backend/app/approval/store.py`

### 7.2 阅读重点

- Tool Definition、工具实例和模型可见工具列表是什么关系？
- deferred 工具为什么能减少常驻 Schema？
- 参数解析、权限、人工审批、超时、执行、记录的先后顺序是什么？
- 为什么工具产生副作用后，Evidence 写入失败不能把整个调用伪装成失败？
- 权限规则冲突时为何 DENY 优先？
- Approval Future 为什么必须在广播前放进 `_pending`？

然后选三个具体工具阅读：

- `backend/app/tools/builtin/read_file.py`
- `backend/app/tools/builtin/write_file.py`
- `backend/app/tools/builtin/shell.py`

配合 `backend/app/tools/builtin/_workspace.py` 理解路径边界。文件工具的路径限制不能直接推广到通用 Shell。

## 8. 第 6 阶段：Planner / Worker

### 8.1 阅读顺序

1. `backend/app/agent/hierarchy.py` 中的系统提示与配置。
2. `WorkerTaskPayload` 和 `WorkerExecutionResult`。
3. `WorkerSubgraph.__init__()` 与 `run()`。
4. `DelegateWorkerTool`。
5. `backend/app/agent/runtime.py` 中创建受限 Worker 的分支。
6. `backend/app/application.py` 中 Planner/Worker 配置解析。
7. `backend/tests/offline/agent/test_agent_hierarchy.py`。

### 8.2 按三层约束理解

| 层次 | 实现 | 作用 |
| --- | --- | --- |
| 任务合同 | Pydantic Payload | 限定委派输入结构 |
| 行为约束 | Planner/Worker system prompt | 告诉模型何时委派、怎样执行 |
| 能力约束 | restricted ToolRegistry | 从程序上移除写入、Shell、再次委派等能力 |

### 8.3 自测问题

- 复杂度判断是确定性代码还是模型行为？
- 为什么 Worker 空历史运行？
- `ContextVar` 防的是什么，并发锁又防什么？
- Worker 为什么仍不等于“完全没有决策”？
- Worker usage 和事件是否已完整合并到主 Run？
- 为什么外层工具超时可能早于 Worker 自己的模型超时？

## 9. 第 7 阶段：上下文管理

### 9.1 阅读顺序

1. `backend/app/context/tokens.py`
2. `backend/app/context/capabilities.py`
3. `backend/app/context/budget.py`
4. `backend/app/context/blocks.py`
5. `backend/app/context/reducers/tool.py`
6. `backend/app/context/reducers/conversation.py`
7. `backend/app/context/manager.py`
8. `backend/app/context/summary.py`
9. `backend/app/context/summary_store.py`

### 9.2 阅读重点

- 原始历史和模型请求视图为何分离？
- 输入预算怎样扣除输出预留与安全余量？
- 为什么先压缩工具结果，再做滚动摘要？
- ToolRoundBlock 怎样保护工具调用与结果配对？
- `covered_message_count` 如何表达摘要覆盖范围？
- 非 OpenAI 模型的 token 数为什么只是保守估算？
- 前缀复用与强制压缩如何同时存在？

阅读测试：`backend/tests/offline/context/`。建议先看 budget、tool reducer、summary 三类测试，再回看 Manager。

## 10. 第 8 阶段：Trace、Checkpoint 与恢复

### 10.1 阅读顺序

1. `backend/app/trace/models.py`
2. `backend/app/trace/store.py`
3. `backend/app/trace/usage.py`
4. `backend/app/checkpoint/models.py`
5. `backend/app/checkpoint/store.py`
6. `backend/app/checkpoint/context.py`
7. `backend/app/run/manager.py`：`interrupt()`、`recover()`、`reconcile()`

### 10.2 重点问题

- Trace 与 Checkpoint 分别用于排障还是恢复？
- 为什么工具执行前和完成后都需要保存边界？
- 重启后 PENDING/RUNNING Run 怎样修正？
- 恢复为什么创建新 Run，而不把旧 Run 改回 RUNNING？
- 外部副作用成功但结果未落库时，为什么不能承诺 exactly-once？

建议手动画一个“工具调用前崩溃、工具调用后崩溃、结果写入后崩溃”的三分图，分别说明恢复策略。

## 11. 第 9 阶段：Memory、Task、Skill

### 11.1 Memory

1. `backend/app/memory/models.py`
2. `backend/app/memory/store.py`
3. `backend/app/memory/core.py`
4. `backend/app/memory/embedding.py`
5. `backend/app/memory/search_index.py`
6. `backend/app/memory/recall.py`
7. `backend/app/memory/manager.py`
8. `backend/app/memory/reflection.py`

重点跟踪：Markdown 事实源 → chunk 索引 → FTS/向量命中 → memory_id 去重 → RRF → 临时上下文注入。

### 11.2 Task

1. `backend/app/task/models.py`
2. `backend/app/task/store.py`
3. `backend/app/task/context.py`
4. `backend/app/task/tools.py`

重点看 revision、单 Task 锁、原子文件替换，以及为什么已完成步骤不能回退。

### 11.3 Skill 与 Skill Learning

1. `backend/app/skills/models.py`
2. `backend/app/skills/parser.py`
3. `backend/app/skills/discovery.py`
4. `backend/app/skills/context.py`
5. `backend/app/skills/tools.py`
6. `backend/app/skill_learning/trace_selector.py`
7. `backend/app/skill_learning/evidence.py`
8. `backend/app/skill_learning/miner.py`
9. `backend/app/skill_learning/distiller.py`
10. `backend/app/skill_learning/service.py`

重点区分：Memory 是事实，Task 是当前进度，Skill 是方法。Skill Learning 生成 Candidate，经过人工确认才成为正式 Skill，不修改模型权重。

## 12. 第 10 阶段：扩展能力

这些模块可以按面试方向选择，不必都在第一周逐行读完。

### 12.1 MCP

1. `backend/app/mcp/models.py`
2. `backend/app/mcp/config.py`
3. `backend/app/mcp/client.py`
4. `backend/app/mcp/manager.py`
5. `backend/app/mcp/tool.py`
6. `backend/app/extensions/importer.py`

关注 stdio 子进程、initialize/list_tools/call_tool、AsyncExitStack、环境变量净化和超时。

### 12.2 Automation

1. `backend/app/automation/models.py`
2. `backend/app/automation/store.py`
3. `backend/app/automation/scheduler.py`
4. `backend/app/automation/tools.py`

关注为什么到点后仍走 ConversationService，以及本地 `_running` 为什么不是分布式锁。

### 12.3 Windows Computer

1. `backend/app/computer/models.py`
2. `backend/app/computer/session.py`
3. `backend/app/computer/windows.py`
4. `backend/app/computer/tools.py`
5. `backend/app/computer/bootstrap.py`
6. `backend/app/sandbox/backends.py`
7. `backend/app/model_settings/secrets.py`

关注 ctypes 的 Win32 声明、GDI 截图、SendInput、to_thread、HWND 局限，以及 pywin32 只用于凭据管理。

## 13. 第 11 阶段：Desktop

先读通信，不要先读 CSS。

1. `desktop/electron/main.ts`
2. `desktop/electron/preload.ts`
3. `desktop/src/main.tsx`
4. `desktop/src/App.tsx`
5. `desktop/src/rpc/protocol.ts`
6. `desktop/src/rpc/client.ts`
7. `desktop/src/rpc/notifications.ts`
8. `desktop/src/api/conversations.ts`
9. `desktop/src/stores/events.ts`
10. `desktop/src/pages/ChatPage.tsx`
11. `desktop/src/components/LiveAgentTurn.tsx`
12. `desktop/src/components/RunActivity.tsx`
13. `desktop/src/components/ApprovalFloatingWindow.tsx`
14. 其余 pages 和 components
15. 最后看 `desktop/src/index.css`

阅读时回答：

- request id 怎样对应 Promise？
- notification 怎样更新实时 Store？
- 重连为什么不自动重发 mutation？
- React Query 和 Zustand 分别管理什么状态？
- Electron 主进程、preload、Renderer 的权限边界是什么？
- `contextIsolation`、`nodeIntegration`、`sandbox` 的实际配置是什么？

## 14. 第 12 阶段：用测试反向验证

测试阅读顺序：

1. `backend/tests/offline/agent/test_agent_hierarchy.py`
2. `backend/tests/offline/agent/test_agent_runtime.py`
3. `backend/tests/offline/tools/test_tools.py`
4. `backend/tests/offline/approval/test_approval.py`
5. `backend/tests/offline/context/`
6. `backend/tests/offline/run/test_run_manager.py`
7. `backend/tests/offline/memory/`
8. `backend/tests/offline/server/test_agent_server.py`
9. `desktop/src/rpc/client.test.ts`
10. 相关组件测试

重点学习 ScriptedAdapter、StubTool、fake MCP server、`tmp_path`、`monkeypatch` 和可注入 socketFactory。这些替身让测试验证控制流而不调用真实模型。

开发检查：

```powershell
cd backend
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m compileall -q app tests

cd ../desktop
npm test
npm run typecheck
npm run build
```

## 15. 一周阅读安排

| 天数 | 内容 | 当天产出 |
| --- | --- | --- |
| Day 1 | 第 0～3 阶段 | 一张主链路图；一分钟介绍 |
| Day 2 | AgentLoop、工具系统 | 一次工具往返时序图 |
| Day 3 | Planner/Worker、上下文 | 权限表；压缩流程图 |
| Day 4 | Trace、Checkpoint、恢复 | 三种崩溃点的恢复说明 |
| Day 5 | Memory、Task、Skill | 三者区别；RRF 公式 |
| Day 6 | MCP、Automation、Windows | 每个模块一个边界说明 |
| Day 7 | Desktop 和测试 | 完整演示；模拟面试问答 |

## 16. 阅读完成标准

当你能脱离源码回答下面问题，说明已经掌握主干：

1. 一条 Desktop 消息经过哪些对象到达模型？
2. 为什么同一 Conversation 串行，不同 Conversation 可以并行？
3. 工具权限、人工审批、执行超时分别在哪一层？
4. Planner 是怎样调用 Worker 的？哪些限制属于硬边界？
5. 为什么工具消息不能按普通消息随意裁剪？
6. 中断恢复为什么不能保证外部副作用恰好一次？
7. Memory 的 FTS 与向量结果如何融合？
8. Skill Learning 为什么需要 Trace 和人工确认？
9. WebSocket 等待长 Run 时为何仍能处理取消？
10. Windows Computer 和 Sandbox 当前分别能保证什么、不能保证什么？

第二遍阅读再关注每个函数的参数、异常和边界条件。源码中的中文 docstring/JSDoc 可以帮助定位，但最终要以调用关系和测试为准。
