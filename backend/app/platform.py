"""Windows 平台能力封装。"""

from __future__ import annotations

import msvcrt
import os
from pathlib import Path
from typing import BinaryIO

WINDOWS = True


def is_windows() -> bool:
    """该构建固定运行在 Windows。"""

    return True

# Windows 缺少下面这些变量时，cmd.exe、PowerShell、node、Python 都无法正常启动。
_WINDOWS_SAFE_KEYS = (
    "ALLUSERSPROFILE",
    "APPDATA",
    "COMMONPROGRAMFILES",
    "COMSPEC",
    "DRIVERDATA",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATHEXT",
    "PATH",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PSMODULEPATH",
    "PUBLIC",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
)


def platform_name() -> str:
    """返回 Pluto 内部使用的平台标识。"""

    return "windows"


def native_shell() -> tuple[str, tuple[str, ...]]:
    """返回当前平台的 (解释器绝对路径或名称, 参数前缀)。

    使用 ``COMSPEC``，找不到时回退到 ``cmd.exe``。
    """

    return os.environ.get("COMSPEC") or "cmd.exe", ("/c",)


def shell_safe_environment() -> dict[str, str]:
    """构造 Shell 子进程的最小安全环境，不向命令暴露 Provider 密钥。"""

    return {
        key: os.environ[key]
        for key in _WINDOWS_SAFE_KEYS
        if os.environ.get(key)
    }


def home_directory() -> str | None:
    """当前 Windows 用户主目录。"""

    return os.environ.get("USERPROFILE")


def package_cache_roots(name: str) -> tuple[str, ...]:
    """返回某个包管理器需要额外开放的缓存目录（可读可写）。

    ``name`` 取值如 ``uv`` / ``node``。
    """

    local_app_data = os.environ.get("LOCALAPPDATA") or ""
    app_data = os.environ.get("APPDATA") or ""
    if name == "uv":
        return (str(Path(local_app_data) / "uv"),)
    if name == "node":
        return (
            str(Path(app_data) / "npm"),
            str(Path(local_app_data) / "npm-cache"),
            str(Path(local_app_data) / "npm" / "node_modules"),
        )
    return ()


def file_lock_available() -> bool:
    """当前平台是否有可用的内核级文件锁。"""

    return True


def lock_file(handle: BinaryIO, *, blocking: bool = True) -> bool:
    """使用 ``msvcrt.locking`` 在文件句柄上加排他锁。

    - 锁第 0 字节，句柄级语义，同进程不同句柄同样互斥；
    - ``blocking=False``：拿不到锁立即返回 False（不抛错）；
      ``blocking=True`` 拿不到锁会等待（Windows 的 LK_LOCK 最多等 10 秒
      后抛 OSError，与 flock 的无限等待略有差异）。

    调用方需保证锁期间文件位置不动（解锁时同样从位置 0 开始）。
    """

    handle.seek(0)
    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
    msvcrt.locking(handle.fileno(), mode, 1)
    return True


def unlock_file(handle: BinaryIO) -> None:
    """释放 ``lock_file`` 加的锁（未加锁 / 平台无锁时静默返回）。"""

    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


__all__ = [
    "WINDOWS",
    "file_lock_available",
    "home_directory",
    "is_windows",
    "lock_file",
    "native_shell",
    "package_cache_roots",
    "platform_name",
    "shell_safe_environment",
    "unlock_file",
]
