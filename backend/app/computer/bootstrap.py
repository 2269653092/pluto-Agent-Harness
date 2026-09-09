"""Windows Computer Runtime bootstrap。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .runtime import ComputerRuntime
from .windows import WindowsComputerRuntime

logger = logging.getLogger("pluto.computer.bootstrap")

ENV_COMPUTER_ENABLED = "PLUTO_COMPUTER_ENABLED"


@dataclass(frozen=True, slots=True)
class ComputerHostStatus:
    """Computer Host 的轻量状态（不持久化，仅供 UI / 日志）。"""

    enabled: bool
    available: bool
    platform: str
    reason: str | None = None
    runtime: str | None = None


def current_platform() -> str:
    return "windows"


def computer_enabled(enabled: bool | None = None) -> bool:
    """Computer 开关：显式参数 > PLUTO_COMPUTER_ENABLED > 默认启用。

    默认启用。
    """

    if enabled is not None:
        return enabled
    raw = os.environ.get(ENV_COMPUTER_ENABLED, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def build_windows_computer(
    *,
    enabled: bool | None = None,
) -> tuple[ComputerRuntime | None, ComputerHostStatus]:
    """构建 WindowsComputerRuntime；显式关闭时返回 (None, disabled status)。"""

    platform = current_platform()
    is_enabled = computer_enabled(enabled)

    if not is_enabled:
        status = ComputerHostStatus(
            enabled=False,
            available=False,
            platform=platform,
            reason="disabled",
        )
        logger.info("Computer disabled; %s", status)
        return None, status

    try:
        runtime = WindowsComputerRuntime()
    except Exception:  # noqa: BLE001 - Win32 初始化失败不应拖垮 Host
        logger.exception("Computer Runtime: Windows initialization failed")
        status = ComputerHostStatus(
            enabled=True,
            available=False,
            platform=platform,
            reason="runtime_init_failed",
        )
        return None, status

    status = ComputerHostStatus(
        enabled=True,
        available=True,
        platform=platform,
        reason=None,
        runtime="windows",
    )
    logger.info("Computer Runtime: Windows available")
    return runtime, status


def build_computer(
    *,
    enabled: bool | None = None,
) -> tuple[ComputerRuntime | None, ComputerHostStatus]:
    """构建 Windows Computer Runtime（统一入口）。"""

    return build_windows_computer(enabled=enabled)


__all__ = [
    "ComputerHostStatus",
    "build_computer",
    "build_windows_computer",
    "computer_enabled",
    "current_platform",
]
