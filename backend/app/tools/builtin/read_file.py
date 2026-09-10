"""仅允许读取 Pluto 工作区的 UTF-8 文本工具。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.models.types import ToolDefinition

from ..base import BaseTool
from ._workspace import resolve_workspace_path, workspace_root_path


class ReadFileTool(BaseTool):
    def __init__(self, workspace_root: str | Path | None = None) -> None:
        """初始化 `ReadFileTool` 实例及其依赖。"""
        self._workspace_root = workspace_root_path(workspace_root)

    @property
    def definition(self) -> ToolDefinition:
        """执行 `definition` 对应的业务逻辑。"""
        return ToolDefinition(
            name="read_file",
            description="Read a UTF-8 text file inside the local workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the workspace.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            strict=True,
        )

    async def execute(self, arguments: dict[str, Any]) -> str:
        """执行`ReadFileTool`的相关流程。"""
        relative_path = arguments.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError("'path' must be a non-empty string")
        target = resolve_workspace_path(self._workspace_root, relative_path)
        return await asyncio.to_thread(_read_utf8_file, target)


def _read_utf8_file(path: Path) -> str:
    """读取 `utf8_file` 对应的数据或流程。"""
    if not path.is_file():
        raise FileNotFoundError(f"file does not exist: {path.name}")
    return path.read_text(encoding="utf-8")
