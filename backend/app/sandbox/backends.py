"""沙箱策略的平台执行后端。"""

from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from .errors import SandboxUnavailableError
from .models import (
    SandboxLaunchSpec,
    SandboxNetworkMode,
    SandboxPolicy,
)

# 网络黑洞：把 HTTP(S) 客户端指向一个必然拒绝连接的本地端口。
# 当前后端使用代理环境变量做尽力而为的网络限制。
_NETWORK_BLACKHOLE_PROXY = "http://127.0.0.1:9"
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "WS_PROXY",
    "WSS_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


class SandboxBackend(ABC):
    """把统一策略编译为实际进程启动参数。"""

    @abstractmethod
    def prepare(
        self,
        *,
        command: Path,
        args: tuple[str, ...],
        env: dict[str, str],
        policy: SandboxPolicy,
    ) -> SandboxLaunchSpec:
        """生成启动规格，不执行进程。"""


class HostSandboxBackend(SandboxBackend):
    """显式关闭隔离时使用；仍保留清理后的环境变量。"""

    def prepare(
        self,
        *,
        command: Path,
        args: tuple[str, ...],
        env: dict[str, str],
        policy: SandboxPolicy,
    ) -> SandboxLaunchSpec:
        return SandboxLaunchSpec(
            command=str(command),
            args=args,
            cwd=str(policy.working_directory),
            env=env,
            backend="host",
            sandboxed=False,
        )


class WindowsRestrictedBackend(SandboxBackend):
    """Windows 受限后端：进程树收束 + 环境变量净化 + 尽力而为的网络限制。

    能强制的部分：
    - 子进程环境只保留执行所需变量（``app.platform.shell_safe_environment``
      之外不追加任何 Provider 密钥）；
    - 工作目录固定到 workspace；
    - 进程退出后由调用方用 ``taskkill /t`` 清理整棵进程树，避免残留子进程。

    不能强制的部分（见 ``docs/sandbox.md``）：
    - 文件系统 ACL：Windows 侧没有等价的轻量 deny-by-default 机制；
    - 网络：只能通过代理环境变量把 HTTP(S) 客户端导向黑洞端口，
      对直接使用 WinSock 的程序无效；
    - 域名白名单：当前无法落实，直接拒绝启动而不是弱化策略。
    """

    def prepare(
        self,
        *,
        command: Path,
        args: tuple[str, ...],
        env: dict[str, str],
        policy: SandboxPolicy,
    ) -> SandboxLaunchSpec:
        if policy.allowed_domains:
            raise SandboxUnavailableError(
                "当前 Windows 后端尚不能强制域名白名单，拒绝弱化网络策略"
            )
        prepared_env = dict(env)
        if policy.network is SandboxNetworkMode.DENIED:
            for key in _PROXY_ENV_KEYS:
                prepared_env[key] = _NETWORK_BLACKHOLE_PROXY
            prepared_env["NO_PROXY"] = ""
            prepared_env["no_proxy"] = ""
        return SandboxLaunchSpec(
            command=str(command),
            args=args,
            cwd=str(policy.working_directory),
            env=prepared_env,
            backend="windows_restricted",
            sandboxed=True,
        )


class UnsupportedSandboxBackend(SandboxBackend):
    """没有可靠平台实现时 fail closed。"""

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def prepare(
        self,
        *,
        command: Path,
        args: tuple[str, ...],
        env: dict[str, str],
        policy: SandboxPolicy,
    ) -> SandboxLaunchSpec:
        del command, args, env, policy
        raise SandboxUnavailableError(
            f"平台 {self.platform!r} 尚无可用的 Pluto 沙箱后端，拒绝降级执行"
        )


def resolve_executable(command: str, *, env: dict[str, str]) -> Path:
    """只接受真实存在的绝对 executable，同时保留虚拟环境入口语义。"""

    candidate = Path(command).expanduser()
    separators = (os.sep, os.altsep) if os.altsep else (os.sep,)
    has_separator = any(separator in command for separator in separators)
    if candidate.is_absolute() or has_separator:
        executable = candidate.absolute()
    else:
        found = shutil.which(command, path=env.get("PATH"))
        if found is None:
            raise SandboxUnavailableError(f"找不到可执行文件：{command}")
        executable = Path(found).absolute()
    try:
        resolved = executable.resolve(strict=True)
    except OSError as exc:
        raise SandboxUnavailableError(f"可执行文件无效：{executable}") from exc
    if not resolved.is_file() or not executable.is_file():
        raise SandboxUnavailableError(f"可执行文件无效：{executable}")
    return executable


__all__ = [
    "HostSandboxBackend",
    "SandboxBackend",
    "UnsupportedSandboxBackend",
    "WindowsRestrictedBackend",
    "resolve_executable",
]
