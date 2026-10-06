"""Scoped memory overview; version-checked mutations live in project_flows."""

from __future__ import annotations

from typing import Any
from app.memory.core import _legacy_content

from ..dispatcher import RpcContext, RpcDispatcher


async def memory_list(
    params: dict[str, Any], ctx: RpcContext
) -> dict[str, Any]:
    """执行 `memory_list` 对应的业务逻辑。"""
    manager = ctx.application.memory_manager
    project_id = None
    if hasattr(ctx.application, "project_services"):
        from .project_flows import services
        service = await services(params, ctx)
        manager = service.memory
        project_id = service.project.id
    if manager is None:
        return {
            "core": "",
            "active": [],
            "archived": [],
            "active_count": 0,
            "max_active": 0,
        }

    core, preferences, version = await manager.core.snapshot()
    active = await manager.list()
    archived = await manager.list_archived()
    return {
        "core": core,
        "legacy_core": _legacy_content(core),
        "preferences": preferences,
        "core_version": version,
        "project_id": project_id,
        "active": [record.model_dump(mode="json") for record in active],
        "archived": [record.model_dump(mode="json") for record in archived],
        "active_count": len(active),
        "max_active": manager.max_active,
    }


def register(dispatcher: RpcDispatcher) -> None:
    """注册当前对象的相关流程。"""
    dispatcher.register("memory.list", memory_list)


__all__ = ["memory_list", "register"]
