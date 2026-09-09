"""Computer Runtime：目标绑定的屏幕观察与 Windows 原生交互。

本轮提供：
- ``models``：Observation / ElementTarget / CoordinateTarget / ActionResult；
- ``runtime``：ComputerRuntime 异步接口（Protocol）；
- ``fake``：FakeComputerRuntime（供 Agent Tool 离线单测使用）；
- ``tools``：computer_observe / click / type / key / scroll / open_app /
  focus_window 七个 Agent 工具 + ``register_computer_tools``；
- ``windows``：WindowsComputerRuntime（Win32 / GDI，进程内实现，无需 helper）。
"""

from .bootstrap import (
    ComputerHostStatus,
    build_computer,
    build_windows_computer,
    computer_enabled,
    current_platform,
)
from .fake import FakeComputerRuntime, default_observation
from .lease import (
    ComputerBusyError,
    ComputerLeaseHook,
    ComputerLeaseManager,
    ComputerLeaseSnapshot,
)
from .models import (
    ActionName,
    ActionResult,
    ActiveApp,
    Bounds,
    CoordinateTarget,
    DeliveryStatus,
    Element,
    ElementStats,
    ElementTarget,
    Observation,
    Target,
    VerificationStatus,
    Window,
)
from .runtime import ComputerRuntime
from .session import (
    ComputerSession,
    ComputerSessionError,
    ComputerSessionManager,
    ComputerSessionMismatchError,
    ComputerSessionNotActiveError,
)
from .tools import (
    ComputerClickTool,
    ComputerFocusWindowTool,
    ComputerKeyTool,
    ComputerObserveTool,
    ComputerOpenAppTool,
    ComputerScrollTool,
    ComputerTypeTool,
    register_computer_tools,
)
from .windows import WindowsComputerRuntime

__all__ = [
    "ActionName",
    "ActionResult",
    "ActiveApp",
    "Bounds",
    "ComputerBusyError",
    "ComputerClickTool",
    "ComputerFocusWindowTool",
    "ComputerHostStatus",
    "ComputerKeyTool",
    "ComputerLeaseHook",
    "ComputerLeaseManager",
    "ComputerLeaseSnapshot",
    "ComputerObserveTool",
    "ComputerOpenAppTool",
    "ComputerRuntime",
    "ComputerScrollTool",
    "ComputerSession",
    "ComputerSessionError",
    "ComputerSessionManager",
    "ComputerSessionMismatchError",
    "ComputerSessionNotActiveError",
    "ComputerTypeTool",
    "CoordinateTarget",
    "DeliveryStatus",
    "Element",
    "ElementStats",
    "ElementTarget",
    "FakeComputerRuntime",
    "Observation",
    "Target",
    "VerificationStatus",
    "Window",
    "WindowsComputerRuntime",
    "build_computer",
    "build_windows_computer",
    "computer_enabled",
    "current_platform",
    "default_observation",
    "register_computer_tools",
]
