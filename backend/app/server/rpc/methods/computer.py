"""computer RPC methods：Windows Host 状态 / 只读最新 Observation。

- ``computer.status``：返回 Windows Computer Runtime 与 Machine Lease 状态。
- ``computer.latest_observation``：从 durable Trace 读取（不调用 runtime.observe，
  不抢 Machine Lease）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.events import AgentEventType

from ..dispatcher import RpcContext, RpcDispatcher
from ..protocol import JsonRpcError, RpcErrorCode

logger = logging.getLogger("pluto.server.rpc.computer")

def _lease_dict(application: Any) -> dict[str, Any] | None:
    """处理 `_lease_dict` 的内部辅助逻辑。"""
    lease = application.computer_lease
    if lease is None:
        return None
    snapshot = lease.snapshot
    if snapshot.owner_run_id is None:
        return None
    return {
        "busy": True,
        "owner_run_id": snapshot.owner_run_id,
        "acquired_at": (
            snapshot.acquired_at.isoformat()
            if snapshot.acquired_at is not None
            else None
        ),
        "process_id": snapshot.process_id,
    }


def _status_dict(
    application: Any,
    *,
    lease: dict[str, Any] | None,
) -> dict[str, Any]:
    """处理 `_status_dict` 的内部辅助逻辑。"""
    host = application.computer_host_status
    if host is None:
        return {
            "enabled": False,
            "available": False,
            "platform": "unknown",
            "runtime": None,
            "reason": "not_configured",
            "lease": lease,
        }
    return {
        "enabled": host.enabled,
        "available": host.available,
        "platform": host.platform,
        "runtime": host.runtime,
        "reason": host.reason,
        "lease": lease,
    }


async def computer_status(
    params: dict[str, Any], ctx: RpcContext
) -> dict[str, Any]:
    """执行 `computer_status` 对应的业务逻辑。"""
    application = ctx.application
    return _status_dict(
        application,
        lease=_lease_dict(application),
    )


def _extract_observation(output: str) -> dict[str, Any] | None:
    """解析 computer_observe 的 ToolResult.output JSON；非法返回 None。"""

    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("id"), str):
        return None
    return payload


async def computer_latest_observation(
    params: dict[str, Any], ctx: RpcContext
) -> dict[str, Any]:
    """执行 `computer_latest_observation` 对应的业务逻辑。"""
    application = ctx.application
    run_id = params.get("run_id")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise JsonRpcError(RpcErrorCode.INVALID_PARAMS, "run_id must be a string")

    if not run_id:
        lease = application.computer_lease
        if lease is not None:
            run_id = lease.snapshot.owner_run_id
        if not run_id:
            return {"run_id": None, "event_time": None, "observation": None}

    trace_store = application.trace_store
    if trace_store is None:
        return {"run_id": run_id, "event_time": None, "observation": None}

    try:
        events = await trace_store.load_events(run_id)
    except Exception as exc:
        logger.warning("computer latest observation load failed: %s", exc)
        return {"run_id": run_id, "event_time": None, "observation": None}

    # 取该 Run 最新一次成功的 computer_observe（从后往前找）。
    for event in reversed(events):
        if event.type is not AgentEventType.TOOL_COMPLETED:
            continue
        if event.tool_call is None or event.tool_result is None:
            continue
        if event.tool_call.name != "computer_observe":
            continue
        if not event.tool_result.success or not event.tool_result.output:
            continue
        observation = _extract_observation(event.tool_result.output)
        if observation is None:
            continue
        return {
            "run_id": run_id,
            "event_time": (
                event.event_time.isoformat()
                if event.event_time is not None
                else None
            ),
            "observation": observation,
        }

    return {"run_id": run_id, "event_time": None, "observation": None}


def register(dispatcher: RpcDispatcher) -> None:
    """注册当前对象的相关流程。"""
    dispatcher.register("computer.status", computer_status)
    dispatcher.register(
        "computer.latest_observation", computer_latest_observation
    )
