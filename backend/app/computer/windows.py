"""真实 Windows ComputerRuntime：直接调用 Win32 / GDI 原生能力。

- 在本进程用 ``EnumWindows`` / ``EnumChildWindows`` 遍历 HWND 树，用
  GDI 截图并通过 ``SendInput`` 投递输入。
- 元素语义是 HWND 级（控件级），不是完整 UIA 树：够支撑
  "观察 → 定位 → 点击 / 输入" 的主链路，但拿不到无句柄控件
  （WPF/Chromium 自绘 UI）的内部节点。
- 修饰键支持 ``ctrl``、``alt``、``shift`` 和 ``win``。

所有阻塞的 Win32 调用都放进 ``asyncio.to_thread``，避免卡住 event loop。
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import subprocess
import uuid
import zlib
from ctypes import wintypes
from pathlib import Path
from typing import Any

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
    VerificationStatus,
    Window,
)
from .session import ComputerSession, ComputerSessionManager

__all__ = ["WindowsComputerRuntime"]

logger = logging.getLogger("pluto.computer.windows")

# 只保留最近若干次 Observation 的 ref→HWND 映射，避免长时间 Run 后无限增长。
_MAX_TRACKED_OBSERVATIONS = 8

# Win32 常量
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1
_BI_RGB = 0
_DIB_RGB_COLORS = 0
_SRCCOPY = 0x00CC0020
_WM_SETTEXT = 0x000C
_WM_GETTEXTLENGTH = 0x000E
_WM_GETTEXT = 0x000D
_WM_CLOSE = 0x0010
_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_KEYEVENTF_SCANCODE = 0x0008
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_WHEEL = 0x0800
_MOUSEEVENTF_ABSOLUTE = 0x8000
_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_LWIN = 0x5B
_MAPVK_VK_TO_VSC = 0
_WHEEL_DELTA = 120

_EDITABLE_CLASS_PREFIXES = ("edit", "richedit", "richedit20", "text")

_ROLE_BY_CLASS = {
    "button": "button",
    "checkbox": "check_box",
    "combobox": "combo_box",
    "listbox": "list",
    "static": "static_text",
    "syslistview32": "list",
    "systreeview32": "tree",
    "systabcontrol32": "tab_group",
    "msctls_trackbar32": "slider",
}

_NAMED_KEYS = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "space": 0x20,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "insert": 0x2D,
}

_MODIFIER_KEYS = {
    "ctrl": _VK_CONTROL,
    "control": _VK_CONTROL,
    "alt": _VK_MENU,
    "shift": _VK_SHIFT,
    "win": _VK_LWIN,
    "super": _VK_LWIN,
}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _encode_png(width: int, height: int, rgb_rows: list[bytes]) -> bytes:
    """把 RGB 行编码成 PNG（只用标准库 zlib，避免新增 Pillow 依赖）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        """执行 `chunk` 对应的业务逻辑。"""
        return (
            len(data).to_bytes(4, "big")
            + tag
            + data
            + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    raw = b"".join(b"\x00" + row for row in rgb_rows)
    header = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            width.to_bytes(4, "big")
            + height.to_bytes(4, "big")
            + b"\x08\x02\x00\x00\x00",
        )
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    return header


class _Win32:
    """Win32 API 的薄封装（惰性加载，非 Windows 平台导入本模块不会炸）。"""

    def __init__(self) -> None:
        """初始化 `_Win32` 实例及其依赖。"""
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._bind()

    def _bind(self) -> None:
        """处理 `_bind` 的内部辅助逻辑。"""
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int
        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        self.user32.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user32.SendInput.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        self.user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
        self.user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self.kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        self.gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self.gdi32.BitBlt.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]

    # -- 窗口信息 ----------------------------------------------------

    def window_title(self, hwnd: int) -> str:
        """执行 `window_title` 对应的业务逻辑。"""
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(length + 1, 1))
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def window_class(self, hwnd: int) -> str:
        """执行 `window_class` 对应的业务逻辑。"""
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    def window_bounds(self, hwnd: int) -> Bounds | None:
        """执行 `window_bounds` 对应的业务逻辑。"""
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return Bounds(
            x=rect.left,
            y=rect.top,
            width=max(rect.right - rect.left, 0),
            height=max(rect.bottom - rect.top, 0),
        )

    def process_id(self, hwnd: int) -> int | None:
        """处理 `id` 对应的数据或流程。"""
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value or None

    def process_name(self, pid: int) -> str:
        # 0x1000 = PROCESS_QUERY_LIMITED_INFORMATION
        """处理 `name` 对应的数据或流程。"""
        handle = self.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(buffer))
            self.kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            named = self.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            )
            if named:
                return Path(buffer.value).name
        finally:
            self.kernel32.CloseHandle(handle)
        return ""

    # -- 输入 --------------------------------------------------------

    def send_input(self, inputs: list[_INPUT]) -> int:
        """执行 `send_input` 对应的业务逻辑。"""
        array = (_INPUT * len(inputs))(*inputs)
        return self.user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))

    def key_input(self, vk: int, *, up: bool = False, scancode: bool = False) -> _INPUT:
        """执行 `key_input` 对应的业务逻辑。"""
        flags = _KEYEVENTF_KEYUP if up else 0
        if scancode:
            flags |= _KEYEVENTF_SCANCODE
            scan = self.user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
        else:
            scan = 0
        entry = _INPUT()
        entry.type = _INPUT_KEYBOARD
        entry.union.ki.wVk = vk
        entry.union.ki.wScan = scan
        entry.union.ki.dwFlags = flags
        return entry

    def unicode_input(self, char: str, *, up: bool = False) -> _INPUT:
        """执行 `unicode_input` 对应的业务逻辑。"""
        flags = _KEYEVENTF_UNICODE | (_KEYEVENTF_KEYUP if up else 0)
        entry = _INPUT()
        entry.type = _INPUT_KEYBOARD
        entry.union.ki.wVk = 0
        entry.union.ki.wScan = ord(char)
        entry.union.ki.dwFlags = flags
        return entry


class WindowsComputerRuntime:
    """用 Win32 API 实现 ComputerRuntime 契约（Windows 原生，无外部 helper）。"""

    def __init__(
        self,
        screenshot_dir: Path | None = None,
        session_manager: ComputerSessionManager | None = None,
    ) -> None:
        """初始化 `WindowsComputerRuntime` 实例及其依赖。"""
        self.screenshot_dir = (
            (
                screenshot_dir
                or Path(__file__).resolve().parents[2]
                / ".pluto"
                / "computer"
                / "screenshots"
            )
            .expanduser()
            .resolve()
        )
        self._session_manager = session_manager or ComputerSessionManager()
        self._win = _Win32()
        # observation_id → {ref: hwnd}
        self._window_handles: dict[str, dict[str, int]] = {}
        self._element_handles: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------
    # Session 生命周期
    # ------------------------------------------------------------------

    def set_session_manager(self, manager: ComputerSessionManager) -> None:
        """由 composition root 注入共享 SessionManager（与 LeaseHook 共用）。"""

        self._session_manager = manager

    def begin_session(self, run_id: str) -> ComputerSession:
        """执行 `begin_session` 对应的业务逻辑。"""
        return self._session_manager.begin(run_id)

    async def begin_session_rpc(self, run_id: str) -> ComputerSession:
        """建立 Session；Windows 没有 helper，无需远程握手。"""

        return await asyncio.to_thread(self._session_manager.begin, run_id)

    async def end_session(self, run_id: str) -> bool:
        """执行 `end_session` 对应的业务逻辑。"""
        return await asyncio.to_thread(self._session_manager.end, run_id)

    async def start(self) -> None:
        """启动`WindowsComputerRuntime`的相关流程。"""
        return None

    async def close(self) -> None:
        """关闭`WindowsComputerRuntime`的相关流程。"""
        self._window_handles.clear()
        self._element_handles.clear()

    def _require_session(self) -> ComputerSession:
        """读取并校验 `session` 对应的数据或流程。"""
        return self._session_manager.require_active()

    def _require_fresh(self) -> tuple[str, Observation]:
        """读取并校验 `fresh` 对应的数据或流程。"""
        session = self._require_session()
        observation = session.current_snapshot
        if observation is None:
            raise ValueError("fresh observation required before computer action")
        return observation.id, observation

    def _invalidate(self) -> None:
        """处理 `_invalidate` 的内部辅助逻辑。"""
        session = self._session_manager.get_active()
        if session is not None:
            session.invalidate_snapshot()

    def _remember(
        self,
        store: dict[str, dict[str, int]],
        key: str,
        mapping: dict[str, int],
    ) -> None:
        """处理 `_remember` 的内部辅助逻辑。"""
        store[key] = mapping
        while len(store) > _MAX_TRACKED_OBSERVATIONS:
            store.pop(next(iter(store)), None)

    # ------------------------------------------------------------------
    # Observe
    # ------------------------------------------------------------------

    async def observe(self, include_screenshot: bool = True) -> Observation:
        """执行 `observe` 对应的业务逻辑。"""
        if not isinstance(include_screenshot, bool):
            raise ValueError("'include_screenshot' must be a boolean")
        session = self._require_session()
        observation_id = uuid.uuid4().hex

        snapshot = await asyncio.to_thread(self._collect_snapshot, observation_id)
        target = snapshot["target"]
        windows = snapshot["windows"]
        elements = snapshot["elements"]
        self._remember(
            self._window_handles, observation_id, snapshot["window_handles"]
        )
        self._remember(
            self._element_handles, observation_id, snapshot["element_handles"]
        )

        screenshot_ref: str | None = None
        if include_screenshot:
            screenshot_ref = await asyncio.to_thread(
                self._write_screenshot, observation_id
            )

        active_window = next(
            (item for item in windows if item.ref == snapshot["active_window_ref"]),
            windows[0] if windows else None,
        )
        observation = Observation(
            id=observation_id,
            active_app=target,
            target=target,
            target_is_frontmost=snapshot["target_is_frontmost"],
            user_frontmost_app=target,
            active_window=active_window,
            windows=windows,
            elements=elements,
            focused_element_ref=snapshot["focused_element_ref"],
            truncated=snapshot["truncated"],
            element_stats=ElementStats(
                observed=snapshot["observed"],
                returned=len(elements),
                editable_count=sum(1 for item in elements if item.editable),
                actionable_count=sum(1 for item in elements if item.actions),
            ),
            screenshot_ref=screenshot_ref,
        )
        if target is not None:
            session.begin_target(target)
        session.previous_user_focus = target
        session.attach_snapshot(observation)
        return observation

    def _collect_snapshot(self, observation_id: str) -> dict[str, Any]:
        """在工作线程里遍历窗口与控件（阻塞调用，不进 event loop）。"""

        win = self._win
        foreground = win.user32.GetForegroundWindow()

        windows: list[Window] = []
        window_handles: dict[str, int] = {}
        collected: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_top(hwnd: int, _lparam: int) -> bool:
            """执行 `enum_top` 对应的业务逻辑。"""
            if not win.user32.IsWindowVisible(hwnd):
                return True
            title = win.window_title(hwnd)
            if not title.strip():
                return True
            bounds = win.window_bounds(hwnd)
            if bounds is None or bounds.width < 1 or bounds.height < 1:
                return True
            collected.append(hwnd)
            return True

        win.user32.EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
            wintypes.LPARAM,
        ]
        win.user32.EnumWindows(enum_top, 0)

        for index, hwnd in enumerate(collected, start=1):
            ref = f"w{index}"
            bounds = win.window_bounds(hwnd) or Bounds(x=0, y=0, width=0, height=0)
            window_handles[ref] = hwnd
            windows.append(Window(ref=ref, title=win.window_title(hwnd), bounds=bounds))

        active_window_ref = next(
            (ref for ref, hwnd in window_handles.items() if hwnd == foreground),
            windows[0].ref if windows else None,
        )

        # 元素：遍历前台窗口（没有前台窗口时退化为第一个可见窗口）的子控件
        root_hwnd = foreground or (collected[0] if collected else 0)
        elements: list[Element] = []
        element_handles: dict[str, int] = {}
        observed = 0
        truncated = False
        if root_hwnd:
            children: list[int] = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def enum_child(hwnd: int, _lparam: int) -> bool:
                """执行 `enum_child` 对应的业务逻辑。"""
                children.append(hwnd)
                return True

            win.user32.EnumChildWindows.argtypes = [
                wintypes.HWND,
                ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
                wintypes.LPARAM,
            ]
            win.user32.EnumChildWindows(root_hwnd, enum_child, 0)

            focus_hwnd = win.user32.GetFocus()
            for index, hwnd in enumerate(children, start=1):
                observed += 1
                if len(elements) >= 200:
                    truncated = True
                    break
                class_name = win.window_class(hwnd)
                lower = class_name.lower()
                role = _ROLE_BY_CLASS.get(lower)
                if role is None:
                    editable = lower.startswith(_EDITABLE_CLASS_PREFIXES)
                    role = "text_field" if editable else lower
                title = win.window_title(hwnd)
                if not title and not lower.startswith(_EDITABLE_CLASS_PREFIXES):
                    continue
                ref = f"e{index}"
                element_handles[ref] = hwnd
                editable = lower.startswith(_EDITABLE_CLASS_PREFIXES)
                elements.append(
                    Element(
                        ref=ref,
                        role=role,
                        title=title or None,
                        value=None,
                        enabled=bool(win.user32.IsWindowEnabled(hwnd)),
                        focused=hwnd == focus_hwnd,
                        editable=editable,
                        bounds=win.window_bounds(hwnd),
                        actions=("press",) if lower == "button" else (),
                    )
                )

        focused_element_ref = next(
            (ref for ref, element in zip(element_handles, elements) if element.focused),
            None,
        )

        pid = win.process_id(foreground) if foreground else None
        name = win.process_name(pid) if pid else ""
        target = ActiveApp(name=name or "unknown", pid=pid)

        return {
            "target": target,
            "target_is_frontmost": bool(foreground),
            "windows": tuple(windows),
            "elements": tuple(elements),
            "window_handles": window_handles,
            "element_handles": element_handles,
            "active_window_ref": active_window_ref,
            "focused_element_ref": focused_element_ref,
            "observed": observed,
            "truncated": truncated,
        }

    def _write_screenshot(self, observation_id: str) -> str | None:
        """抓取主显示器并写成 PNG，返回 observation_id（失败返回 None）。"""

        win = self._win
        width = win.user32.GetSystemMetrics(_SM_CXSCREEN)
        height = win.user32.GetSystemMetrics(_SM_CYSCREEN)
        if width <= 0 or height <= 0:
            return None

        hdc_screen = win.user32.GetDC(0)
        if not hdc_screen:
            return None
        hdc_mem = win.gdi32.CreateCompatibleDC(hdc_screen)
        if not hdc_mem:
            win.user32.ReleaseDC(0, hdc_screen)
            return None

        header = (ctypes.c_uint32 * 10)()
        # BITMAPINFOHEADER：负 biHeight 表示自上而下的 DIB，省掉翻转步骤。
        header[0] = 40  # biSize
        header[1] = width  # biWidth
        header[2] = (-height) & 0xFFFFFFFF  # biHeight（负数 → 自上而下 DIB）
        header[3] = (32 << 16) | 1  # 低 WORD = biPlanes=1，高 WORD = biBitCount=32
        header[4] = _BI_RGB

        bits = ctypes.c_void_p()
        win.gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        win.gdi32.CreateDIBSection.restype = wintypes.HANDLE
        bitmap = win.gdi32.CreateDIBSection(
            hdc_mem,
            header,
            _DIB_RGB_COLORS,
            ctypes.byref(bits),
            None,
            0,
        )
        if not bitmap or not bits:
            win.gdi32.DeleteDC(hdc_mem)
            win.user32.ReleaseDC(0, hdc_screen)
            return None

        try:
            win.gdi32.SelectObject(hdc_mem, bitmap)
            if not win.gdi32.BitBlt(
                hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, _SRCCOPY
            ):
                return None
            stride = width * 4
            buffer = ctypes.create_string_buffer(stride * height)
            ctypes.memmove(buffer, bits, stride * height)
        finally:
            win.gdi32.DeleteObject(bitmap)
            win.gdi32.DeleteDC(hdc_mem)
            win.user32.ReleaseDC(0, hdc_screen)

        raw = bytes(buffer)
        rows: list[bytes] = []
        for y in range(height):
            row = bytearray(width * 3)
            offset = y * stride
            for x in range(width):
                base = offset + x * 4
                row[x * 3] = raw[base + 2]  # BGR0 → RGB
                row[x * 3 + 1] = raw[base + 1]
                row[x * 3 + 2] = raw[base]
            rows.append(bytes(row))

        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        (self.screenshot_dir / f"{observation_id}.png").write_bytes(
            _encode_png(width, height, rows)
        )
        return observation_id

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def click(self, target: ElementTarget | CoordinateTarget) -> ActionResult:
        """执行 `click` 对应的业务逻辑。"""
        if isinstance(target, ElementTarget):
            handles = self._element_handles.get(target.observation_id)
            hwnd = handles.get(target.element_ref) if handles else None
            if hwnd is None:
                raise ValueError(
                    "element_ref does not belong to the latest observation; "
                    "recovery: call computer_observe again"
                )
            await asyncio.to_thread(self._click_hwnd, hwnd)
            self._invalidate()
            return ActionResult(
                success=True,
                action=ActionName.CLICK,
                observation_id=target.observation_id,
                delivery_status=DeliveryStatus.DELIVERED,
                method="hwnd_coordinate",
                execution_mode="foreground_fallback",
                metadata={"element_ref": target.element_ref, "hwnd": hwnd},
            )
        if isinstance(target, CoordinateTarget):
            await asyncio.to_thread(self._click_coordinate, target.x, target.y)
            self._invalidate()
            return ActionResult(
                success=True,
                action=ActionName.CLICK,
                observation_id=target.observation_id,
                delivery_status=DeliveryStatus.DELIVERED,
                method="coordinate",
                execution_mode="foreground_fallback",
                metadata={"x": target.x, "y": target.y},
            )
        raise ValueError("unsupported click target")

    def _click_hwnd(self, hwnd: int) -> None:
        """处理 `_click_hwnd` 的内部辅助逻辑。"""
        win = self._win
        win.user32.SetForegroundWindow(hwnd)
        bounds = win.window_bounds(hwnd)
        if bounds is None:
            return
        self._click_coordinate(
            bounds.x + bounds.width // 2,
            bounds.y + bounds.height // 2,
        )

    def _click_coordinate(self, x: int, y: int) -> None:
        """处理 `_click_coordinate` 的内部辅助逻辑。"""
        win = self._win
        win.user32.SetCursorPos(x, y)
        inputs = [
            self._mouse_input(_MOUSEEVENTF_LEFTDOWN),
            self._mouse_input(_MOUSEEVENTF_LEFTUP),
        ]
        win.send_input(inputs)

    def _mouse_input(self, flags: int, *, data: int = 0) -> _INPUT:
        """处理 `_mouse_input` 的内部辅助逻辑。"""
        entry = _INPUT()
        entry.type = _INPUT_MOUSE
        entry.union.mi.dx = 0
        entry.union.mi.dy = 0
        entry.union.mi.mouseData = data
        entry.union.mi.dwFlags = flags
        return entry

    async def type(
        self,
        text: str,
        element_ref: str | None = None,
    ) -> ActionResult:
        """执行 `type` 对应的业务逻辑。"""
        if not isinstance(text, str):
            raise ValueError("'text' must be a string")
        observation_id, observation = self._require_fresh()
        handles = self._element_handles.get(observation_id, {})
        hwnd = handles.get(element_ref) if element_ref else None
        if element_ref is not None and hwnd is None:
            raise ValueError(
                "element_ref does not belong to the latest observation; "
                "recovery: call computer_observe again"
            )
        delivered = await asyncio.to_thread(self._send_text, text, hwnd)
        if text:
            self._invalidate()
        return ActionResult(
            success=delivered,
            action=ActionName.TYPE,
            observation_id=observation_id,
            delivery_status=(
                DeliveryStatus.DELIVERED if delivered else DeliveryStatus.FAILED
            ),
            verification_status=VerificationStatus.UNVERIFIED,
            method="send_input_unicode",
            execution_mode="foreground_fallback",
            metadata={"characters": len(text), "element_ref": element_ref},
        )

    def _send_text(self, text: str, hwnd: int | None) -> bool:
        """处理 `_send_text` 的内部辅助逻辑。"""
        win = self._win
        if hwnd:
            win.user32.SetForegroundWindow(hwnd)
        inputs: list[_INPUT] = []
        for char in text:
            if char in ("\n", "\r"):
                inputs.append(win.key_input(_NAMED_KEYS["enter"]))
                inputs.append(win.key_input(_NAMED_KEYS["enter"], up=True))
                continue
            if char == "\t":
                inputs.append(win.key_input(_NAMED_KEYS["tab"]))
                inputs.append(win.key_input(_NAMED_KEYS["tab"], up=True))
                continue
            inputs.append(win.unicode_input(char))
            inputs.append(win.unicode_input(char, up=True))
        if not inputs:
            return True
        sent = win.send_input(inputs)
        return sent >= len(inputs)

    async def key(
        self,
        key: str,
        modifiers: tuple[str, ...] = (),
        element_ref: str | None = None,
    ) -> ActionResult:
        """执行 `key` 对应的业务逻辑。"""
        if not isinstance(key, str) or not key.strip():
            raise ValueError("'key' must be a non-empty string")
        if not isinstance(modifiers, tuple) or not all(
            isinstance(item, str) for item in modifiers
        ):
            raise ValueError("'modifiers' must be a tuple of strings")
        observation_id, _ = self._require_fresh()
        handles = self._element_handles.get(observation_id, {})
        hwnd = handles.get(element_ref) if element_ref else None
        if element_ref is not None and hwnd is None:
            raise ValueError(
                "element_ref does not belong to the latest observation; "
                "recovery: call computer_observe again"
            )
        delivered = await asyncio.to_thread(self._send_key, key, modifiers, hwnd)
        self._invalidate()
        return ActionResult(
            success=delivered,
            action=ActionName.KEY,
            observation_id=observation_id,
            delivery_status=(
                DeliveryStatus.DELIVERED if delivered else DeliveryStatus.FAILED
            ),
            method="send_input_vk",
            execution_mode="foreground_fallback",
            metadata={"key": key, "modifiers": list(modifiers)},
        )

    def _send_key(
        self,
        key: str,
        modifiers: tuple[str, ...],
        hwnd: int | None,
    ) -> bool:
        """处理 `_send_key` 的内部辅助逻辑。"""
        win = self._win
        if hwnd:
            win.user32.SetForegroundWindow(hwnd)
        normalized = key.strip().lower()
        vk = _NAMED_KEYS.get(normalized)
        if vk is None:
            vk = self._virtual_key_for_char(key)
            if vk is None:
                raise ValueError(f"unsupported key: {key}")

        modifier_vks: list[int] = []
        for item in modifiers:
            modifier_vk = _MODIFIER_KEYS.get(item.strip().lower())
            if modifier_vk is None:
                raise ValueError(f"unsupported modifier: {item}")
            modifier_vks.append(modifier_vk)

        inputs: list[_INPUT] = [win.key_input(item) for item in modifier_vks]
        inputs.append(win.key_input(vk))
        inputs.append(win.key_input(vk, up=True))
        inputs.extend(win.key_input(item, up=True) for item in reversed(modifier_vks))
        sent = win.send_input(inputs)
        return sent >= len(inputs)

    def _virtual_key_for_char(self, char: str) -> int | None:
        """处理 `_virtual_key_for_char` 的内部辅助逻辑。"""
        if len(char) != 1:
            return None
        scan = self._win.user32.VkKeyScanW(char)
        if scan == -1:
            return None
        return scan & 0xFF

    async def scroll(self, delta_x: int = 0, delta_y: int = 0) -> ActionResult:
        """执行 `scroll` 对应的业务逻辑。"""
        for name, value in (("delta_x", delta_x), ("delta_y", delta_y)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"'{name}' must be an integer")
        if delta_x == 0 and delta_y == 0:
            raise ValueError("at least one scroll delta must be non-zero")
        observation_id, _ = self._require_fresh()
        await asyncio.to_thread(self._send_scroll, delta_y)
        self._invalidate()
        return ActionResult(
            success=True,
            action=ActionName.SCROLL,
            observation_id=observation_id,
            delivery_status=DeliveryStatus.DELIVERED,
            method="mouse_wheel",
            execution_mode="foreground_fallback",
            metadata={"delta_x": delta_x, "delta_y": delta_y},
        )

    def _send_scroll(self, delta_y: int) -> None:
        # Windows 滚轮以 120 为一格，向上为正；工具参数约定向下为正。
        """处理 `_send_scroll` 的内部辅助逻辑。"""
        notches = -delta_y // _WHEEL_DELTA or (-1 if delta_y > 0 else 1)
        notches = max(min(notches, 10), -10)
        entry = _INPUT()
        entry.type = _INPUT_MOUSE
        entry.union.mi.mouseData = notches * _WHEEL_DELTA
        entry.union.mi.dwFlags = _MOUSEEVENTF_WHEEL
        self._win.send_input([entry])

    async def open_app(self, app: str) -> ActionResult:
        """执行 `open_app` 对应的业务逻辑。"""
        if not isinstance(app, str) or not app.strip():
            raise ValueError("'app' must be a non-empty string")
        session = self._require_session()
        launched = await asyncio.to_thread(self._launch_app, app)
        self._invalidate()
        target = ActiveApp(
            name=launched["name"] or app,
            pid=launched["pid"],
        )
        session.begin_target(target)
        return ActionResult(
            success=launched["pid"] is not None,
            action=ActionName.OPEN_APP,
            method="shell_execute",
            execution_mode="foreground_fallback",
            metadata={
                "app": app,
                "process_id": launched["pid"],
                "launch_status": "running" if launched["pid"] else "failed",
            },
        )

    def _launch_app(self, app: str) -> dict[str, Any]:
        """启动应用：优先直接执行，其次交给 Shell 关联打开。"""

        path = Path(app)
        if path.is_file():
            process = subprocess.Popen([str(path)], shell=False)  # noqa: S603
            return {"pid": process.pid, "name": path.name}
        try:
            process = subprocess.Popen(app, shell=False)  # noqa: S603
            return {"pid": process.pid, "name": app}
        except (OSError, ValueError):
            pass
        try:
            os.startfile(app)  # noqa: S606 - 由用户/模型显式指定，走 Shell 关联
        except OSError as exc:
            logger.warning("failed to open app %s: %s", app, exc)
            return {"pid": None, "name": app}
        return {"pid": None, "name": app}

    async def focus_window(self, window_ref: str) -> ActionResult:
        """执行 `focus_window` 对应的业务逻辑。"""
        if not isinstance(window_ref, str) or not window_ref.strip():
            raise ValueError("'window_ref' must be a non-empty string")
        observation_id, _ = self._require_fresh()
        handles = self._window_handles.get(observation_id, {})
        hwnd = handles.get(window_ref.strip())
        if hwnd is None:
            raise ValueError(
                "window_ref does not belong to the latest observation; "
                "recovery: call computer_observe again"
            )
        activated = await asyncio.to_thread(
            self._win.user32.SetForegroundWindow, hwnd
        )
        self._invalidate()
        return ActionResult(
            success=bool(activated),
            action=ActionName.FOCUS_WINDOW,
            observation_id=observation_id,
            method="set_foreground_window",
            execution_mode="foreground_fallback",
            metadata={"window_ref": window_ref, "hwnd": hwnd},
        )
