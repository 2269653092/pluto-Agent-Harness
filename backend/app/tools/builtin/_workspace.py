"""内置文件工具共用的工作区路径校验。"""

from __future__ import annotations

from pathlib import Path


def workspace_root_path(workspace_root: str | Path | None) -> Path:
    """执行 `workspace_root_path` 对应的业务逻辑。"""
    if workspace_root is None:
        workspace_root = Path(__file__).resolve().parents[4] / "workspace"
    return Path(workspace_root).resolve()


def resolve_workspace_path(
    workspace_root: Path,
    relative_path: str,
    *,
    allow_root: bool = False,
) -> Path:
    """解析或确定 `workspace_path` 对应的数据或流程。"""
    requested = Path(relative_path)
    if requested.is_absolute():
        raise ValueError("path must be relative to the workspace")

    resolved = (workspace_root / requested).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        raise ValueError("path escapes the workspace") from None

    if not allow_root and resolved == workspace_root:
        raise ValueError("path must reference an item inside the workspace")
    return resolved
