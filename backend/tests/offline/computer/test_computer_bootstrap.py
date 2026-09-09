"""Windows Computer bootstrap 测试。"""

from __future__ import annotations

from app.computer.bootstrap import (
    build_computer,
    build_windows_computer,
    computer_enabled,
    current_platform,
)
from app.computer.windows import WindowsComputerRuntime


def test_disabled_does_not_build_runtime() -> None:
    runtime, status = build_windows_computer(enabled=False)
    assert runtime is None
    assert status.enabled is False
    assert status.available is False
    assert status.reason == "disabled"
    assert status.platform == "windows"


def test_build_windows_runtime() -> None:
    runtime, status = build_windows_computer(enabled=True)
    assert isinstance(runtime, WindowsComputerRuntime)
    assert status.enabled is True
    assert status.available is True
    assert status.reason is None
    assert status.platform == "windows"
    assert status.runtime == "windows"


def test_build_computer_uses_windows_runtime() -> None:
    runtime, status = build_computer(enabled=True)
    assert isinstance(runtime, WindowsComputerRuntime)
    assert status.runtime == "windows"


def test_computer_enabled_switch_and_env(monkeypatch) -> None:
    assert computer_enabled() is True
    assert computer_enabled(enabled=False) is False
    assert computer_enabled(enabled=True) is True

    monkeypatch.setenv("PLUTO_COMPUTER_ENABLED", "false")
    assert computer_enabled() is False
    monkeypatch.setenv("PLUTO_COMPUTER_ENABLED", "true")
    assert computer_enabled() is True


def test_current_platform_is_windows() -> None:
    assert current_platform() == "windows"
