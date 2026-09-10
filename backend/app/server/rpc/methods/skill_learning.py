"""桌面端 Skill Learning：单任务生成候选与人工审核。"""

from __future__ import annotations

from typing import Any

from app.skill_learning import SkillLearningService

from ..dispatcher import RpcContext, RpcDispatcher
from ..protocol import (
    INVALID_STATE,
    RESOURCE_NOT_FOUND,
    JsonRpcError,
    RpcErrorCode,
)


def _service(ctx: RpcContext) -> SkillLearningService:
    """获取已初始化的 Skill Learning Service。"""

    service = ctx.application.skill_learning
    if service is None:
        raise JsonRpcError(
            RpcErrorCode.INTERNAL_ERROR,
            "Skill Learning Service unavailable",
        )
    return service


async def skill_learning_generate(
    params: dict[str, Any],
    ctx: RpcContext,
) -> dict[str, Any]:
    """从指定当前任务的执行记录生成待审核 Skill Candidate。"""

    try:
        candidate, created, message = await _service(ctx).generate_for_task(
            _require_str(params, "task_id")
        )
    except KeyError as exc:
        raise JsonRpcError(RESOURCE_NOT_FOUND, "task not found") from exc
    except ValueError as exc:
        raise JsonRpcError(INVALID_STATE, str(exc)) from exc
    except RuntimeError as exc:
        raise JsonRpcError(INVALID_STATE, f"Skill 提炼失败：{exc}") from exc
    return {
        "candidate": (
            candidate.model_dump(mode="json") if candidate is not None else None
        ),
        "created": created,
        "message": message,
    }


async def skill_learning_accept(
    params: dict[str, Any],
    ctx: RpcContext,
) -> dict[str, Any]:
    """在用户明确确认后把候选写入正式 Skill。"""

    if params.get("confirmed") is not True:
        raise JsonRpcError(
            RpcErrorCode.INVALID_PARAMS,
            "必须明确确认后才能保存正式 Skill",
        )
    scope = params.get("scope")
    if scope is not None and not isinstance(scope, str):
        raise JsonRpcError(RpcErrorCode.INVALID_PARAMS, "scope must be a string")
    try:
        candidate, target = await _service(ctx).accept(
            _require_str(params, "candidate_id"),
            scope=scope,
        )
    except KeyError as exc:
        raise JsonRpcError(RESOURCE_NOT_FOUND, "candidate not found") from exc
    except (OSError, ValueError) as exc:
        raise JsonRpcError(INVALID_STATE, str(exc)) from exc
    return {
        "candidate": candidate.model_dump(mode="json"),
        "path": str(target) if target is not None else None,
    }


async def skill_learning_reject(
    params: dict[str, Any],
    ctx: RpcContext,
) -> dict[str, Any]:
    """拒绝一个待审核 Skill Candidate。"""

    try:
        candidate = await _service(ctx).reject(
            _require_str(params, "candidate_id")
        )
    except KeyError as exc:
        raise JsonRpcError(RESOURCE_NOT_FOUND, "candidate not found") from exc
    except ValueError as exc:
        raise JsonRpcError(INVALID_STATE, str(exc)) from exc
    return {"candidate": candidate.model_dump(mode="json")}


def _require_str(params: dict[str, Any], key: str) -> str:
    """读取并校验必填字符串参数。"""

    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise JsonRpcError(RpcErrorCode.INVALID_PARAMS, f"{key} is required")
    return value.strip()


def register(dispatcher: RpcDispatcher) -> None:
    """注册桌面端 Skill Learning RPC。"""

    dispatcher.register("skill_learning.generate", skill_learning_generate)
    dispatcher.register("skill_learning.accept", skill_learning_accept)
    dispatcher.register("skill_learning.reject", skill_learning_reject)


__all__ = ["register"]
