# Pluto Sandbox

Sandbox 保护能够执行任意代码的入口，不改变 AgentRuntime 的 `ToolCall → ToolResult`
协议。权限审批回答“是否允许做”，Sandbox 回答“获准后最多能影响哪里”。

## 当前覆盖范围

- `run_shell_command`：workspace 可读写，网络默认拒绝，使用 `cmd.exe` 执行；
- 第三方 stdio MCP Server：使用 Windows 受限后端；
- MCP 环境变量：只继承 SYSTEMROOT / PATH / TEMP 等系统运行必需项，
  配置中的 `${ENV_NAME}` 按需注入；
- `.git`、`.pluto`、`.env` 等控制边界和敏感文件在 workspace 内继续拒绝读取或写入；
- 沙箱不可用、路径无效或策略无法强制时 fail closed。

受控的内置文件、Task、Memory、Artifact 和 Search 工具继续在 Host 中执行，它们通过窄接口
和领域校验限制能力。Computer Runtime 必须操作真实桌面，继续依赖审批、ComputerSession、
exact target、fresh observation 和执行后验证。

## 执行链

```text
ToolCall
  ↓
Permission / Approval
  ↓
ShellCommandTool 或 StdioMCPClient
  ↓
SandboxSupervisor
  ├─ 解析 executable 与工作目录
  ├─ 编译读写根、敏感路径和网络策略
  ├─ 清理环境变量
  └─ 选择平台 Backend
        ↓
Windows 受限后端 → 子进程树
```

MCP 默认配置：

```json
{
  "sandbox": {
    "filesystem": "workspace_write",
    "network": "unrestricted",
    "readable_roots": [],
    "writable_roots": [],
    "allowed_domains": []
  }
}
```

`filesystem` 支持：

- `none`：不暴露 workspace；
- `read_only`：workspace 只读；
- `workspace_write`：workspace 可读写，默认值；
- `host`：显式关闭 OS 隔离，仅供用户确认过的可信进程使用。

`network` 当前支持 `denied` 和 `unrestricted`。`allowed_domains` 已进入稳定配置模型，但在域名
代理完成前不能被可靠强制；配置非空时拒绝启动，避免把白名单请求弱化成全网访问。

## Windows 后端（WindowsRestrictedBackend）

能强制：

- 子进程环境只保留执行必需变量，不透传 Provider 密钥；
- 工作目录固定到 workspace；
- 进程退出后由调用方用 `taskkill /t` 清理整棵进程树。

不能强制：

- 文件系统 ACL：没有轻量的 deny-by-default 机制，不保证 workspace 外读不到；
- 网络：只把 HTTP(S) 代理环境变量指向黑洞端口（127.0.0.1:9），
  对直接使用 WinSock 的程序无效；
- 域名白名单：当前无法落实，直接拒绝启动而不是弱化策略。

## 运行时缓存根

仅为检测到的包管理器开放必要缓存目录，不开放整个用户主目录：

- `%LOCALAPPDATA%\uv`
- `%APPDATA%\npm`
- `%LOCALAPPDATA%\npm-cache`

uv/npm 的缓存写权限用于现有 `uvx` / `npx` MCP 启动兼容，不代表这些进程可以访问 SSH、
浏览器或系统凭据数据。

## 尚未实现

- Docker/Podman 严格隔离后端；
- 基于代理的域名 allowlist；
- CPU、内存、磁盘与进程数量限制；
- Skill 脚本的独立执行入口；
- 每个 MCP Server 独立的包缓存目录。

未来执行后端可以替换，但上层 Policy、MCP、ToolResult、Approval 和 Trace 语义
保持不变。
