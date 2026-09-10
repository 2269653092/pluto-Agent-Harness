"""Planner 主图与禁止递归委派的全工具 Worker 子图。"""

from __future__ import annotations

import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.context import ContextManager
from app.models.config import ModelSettings
from app.models.registry import ModelAdapterRegistry
from app.models.types import AgentMode, ModelProvider, ToolDefinition
from app.tools.base import BaseTool
from app.tools.executor import ToolExecutor
from app.tools.hooks import ToolExecutionContext
from app.tools.registry import ToolRegistry

from .budget import RunBudget
from .event_stream import EventEmitter
from .events import NullEventHandler
from .loop import AgentLoop

_BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

DELEGATE_WORKER_TOOL_NAME = "delegate_to_worker"
WORKER_FORBIDDEN_TOOL_NAMES = frozenset({DELEGATE_WORKER_TOOL_NAME})

PLANNER_SYSTEM_PROMPT_MARKER = "[Pluto Planner Role]"
PLANNER_SYSTEM_PROMPT = f"""
{PLANNER_SYSTEM_PROMPT_MARKER}
你是分层 Agent 架构中的主管 Agent（Planner）。你对最终结果负责，并拥有完整工具权限。
收到目标后先判断复杂度和风险：
- 复杂、模糊、高风险、需要跨步骤决策或需要写入环境的工作，由你自己规划并继续处理。
- 边界清晰、低风险、可独立验收的简单任务或简单子任务，必须调用
  `{DELEGATE_WORKER_TOOL_NAME}`，把目标、逐条指令、约束、上下文和期望输出打包成标准载荷。
- 不要把整体复杂任务、任务规划、权限判断或最终答复责任下放给 Worker。
Worker 返回后，你必须检查结果是否满足载荷，再由你汇总并向用户输出最终答案。
Worker 结果只是子图执行结果，不能替代你的最终判断。
""".strip()

WORKER_SYSTEM_PROMPT = """
[Pluto Worker Role]
你是分层 Agent 架构中的工人 Agent（Worker）。上游已经完成规划和判断。
你只能执行收到的标准 task_payload，不得重新规划、扩展范围、改变目标或创建/委派子任务。
严格按 instructions 和 constraints 执行；可以使用运行时提供的全部工具，但绝对禁止
调用、创建或委派另一个 Worker/子代理，也不得通过其他工具规避这条限制。
缺少完成任务所必需的信息时，明确返回缺失项，不要自行猜测或扩大任务。
最终只返回可供 Planner 验收和汇总的执行结果，不直接面向最终用户做决策。
""".strip()


class AgentHierarchySettings(BaseSettings):
    """从 ``backend/.env`` 读取 Planner / Worker 独立模型配置。"""

    model_config = SettingsConfigDict(
        env_file=_BACKEND_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    agent_hierarchy_enabled: bool = True

    planner_provider: ModelProvider | None = None
    planner_model: str | None = None
    planner_api_key: SecretStr | None = None
    planner_base_url: str | None = None

    worker_provider: ModelProvider | None = None
    worker_model: str | None = None
    worker_api_key: SecretStr | None = None
    worker_base_url: str | None = None
    worker_max_steps: int = Field(default=4, ge=1, le=8)
    worker_max_tool_rounds: int = Field(default=3, ge=1, le=6)
    worker_max_output_tokens: int = Field(default=2048, ge=128)

    def planner_model_settings(self, base: ModelSettings) -> ModelSettings:
        """生成 Planner 专属设置，未配置项回退到现有 Provider 设置。"""

        return self._role_model_settings(base, role="planner")

    def worker_model_settings(
        self,
        base: ModelSettings,
        *,
        planner: ModelSettings,
    ) -> ModelSettings:
        """生成 Worker 专属设置，Provider 默认跟随 Planner。"""

        return self._role_model_settings(base, role="worker", planner=planner)

    def _role_model_settings(
        self,
        base: ModelSettings,
        *,
        role: Literal["planner", "worker"],
        planner: ModelSettings | None = None,
    ) -> ModelSettings:
        """处理 `_role_model_settings` 的内部辅助逻辑。"""
        fallback_provider = (
            planner.model_default_provider
            if role == "worker" and planner is not None
            else base.model_default_provider
        )
        provider = getattr(self, f"{role}_provider") or fallback_provider
        prefix = provider.value
        data = base.model_dump(mode="python")
        data["model_default_provider"] = provider

        model = _non_empty(getattr(self, f"{role}_model"))
        base_url = _non_empty(getattr(self, f"{role}_base_url"))
        api_key = _secret_value(getattr(self, f"{role}_api_key"))
        if model is not None:
            data[f"{prefix}_model"] = model
        if base_url is not None:
            data[f"{prefix}_base_url"] = base_url
        if api_key is not None:
            data[f"{prefix}_api_key"] = SecretStr(api_key)
        return ModelSettings.model_validate(data)


class WorkerTaskPayload(BaseModel):
    """Planner 下发给 Worker 的固定、可审计任务合同。"""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=2000)
    instructions: tuple[str, ...] = Field(min_length=1, max_length=12)
    expected_output: str = Field(min_length=1, max_length=2000)
    constraints: tuple[str, ...] = Field(default=(), max_length=12)
    context: str | None = Field(default=None, max_length=8000)

    def worker_input(self) -> str:
        """执行 `worker_input` 对应的业务逻辑。"""
        return (
            "执行以下由 Planner 已规划好的 task_payload。不要重新规划或扩展范围。\n"
            + json.dumps(self.model_dump(exclude_none=True), ensure_ascii=False)
        )


class WorkerExecutionResult(BaseModel):
    """Worker 子图返回给 Planner 的标准结果。"""

    model_config = ConfigDict(extra="forbid")

    success: bool
    output: str | None = None
    stop_reason: str
    steps: int = Field(ge=0)
    usage: dict[str, Any]
    error: str | None = None


class WorkerSubgraph:
    """同一 AgentRuntime 内运行的受限 Worker AgentLoop。"""

    def __init__(
        self,
        model_registry: ModelAdapterRegistry,
        tool_registry: ToolRegistry,
        *,
        provider: ModelProvider | str,
        model: str | None,
        max_steps: int,
        max_tool_rounds: int,
        max_output_tokens: int,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """初始化 `WorkerSubgraph` 实例及其依赖。"""
        forbidden = WORKER_FORBIDDEN_TOOL_NAMES.intersection(tool_registry.names())
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ValueError(f"Worker registry contains forbidden tools: {names}")
        self._tool_registry = tool_registry
        self._executor = tool_executor or ToolExecutor(tool_registry)
        self._loop = AgentLoop(
            model_registry=model_registry,
            tool_registry=tool_registry,
            tool_executor=self._executor,
            provider=provider,
            model=model,
            system_prompt=WORKER_SYSTEM_PROMPT,
            max_steps=max_steps,
            max_tool_rounds=max_tool_rounds,
            max_output_tokens=max_output_tokens,
            context_manager=ContextManager(),
            task_context_provider=None,
            checkpoint_store=None,
            memory_manager=None,
            skill_store=None,
            skill_context_provider=None,
            run_budget=RunBudget(),
        )
        self._depth: ContextVar[int] = ContextVar("pluto_worker_depth", default=0)

    @property
    def tool_names(self) -> tuple[str, ...]:
        """执行 `tool_names` 对应的业务逻辑。"""
        return self._tool_registry.names()

    async def run(
        self,
        payload: WorkerTaskPayload,
        *,
        parent_run_id: str | None,
        conversation_id: str | None,
    ) -> WorkerExecutionResult:
        """运行`WorkerSubgraph`的相关流程。"""
        depth = self._depth.get()
        if depth:
            raise RuntimeError("Worker cannot create or invoke another Worker")
        token = self._depth.set(depth + 1)
        worker_run_id = f"{parent_run_id or 'worker'}:worker:{uuid4().hex[:8]}"
        emitter = EventEmitter(
            handler=NullEventHandler(),
            run_id=worker_run_id,
            conversation_id=conversation_id,
        )
        try:
            result = await self._loop.run(
                worker_run_id,
                payload.worker_input(),
                history=(),
                conversation_id=conversation_id,
                emitter=emitter,
                summary_state=None,
                recovery_checkpoint=None,
                mode=AgentMode.NORMAL,
            )
            return WorkerExecutionResult(
                success=result.ok,
                output=result.content,
                stop_reason=result.stop_reason.value,
                steps=result.steps,
                usage=result.usage.model_dump(mode="json"),
                error=result.error.message if result.error is not None else None,
            )
        finally:
            await self._executor.clear_run_rules(worker_run_id)
            self._depth.reset(token)


class DelegateWorkerTool(BaseTool):
    """Planner 调用 Worker 子图的唯一入口。"""

    def __init__(self, worker: WorkerSubgraph) -> None:
        """初始化 `DelegateWorkerTool` 实例及其依赖。"""
        self._worker = worker

    @property
    def definition(self) -> ToolDefinition:
        """执行 `definition` 对应的业务逻辑。"""
        return ToolDefinition(
            name=DELEGATE_WORKER_TOOL_NAME,
            description=(
                "Delegate one already-planned, simple, bounded subtask to the "
                "non-delegating Worker Agent and return its result."
            ),
            parameters=WorkerTaskPayload.model_json_schema(),
            strict=True,
        )

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行`DelegateWorkerTool`的相关流程。"""
        payload = WorkerTaskPayload.model_validate(arguments)
        result = await self._worker.run(
            payload,
            parent_run_id=None,
            conversation_id=None,
        )
        return result.model_dump(mode="json", exclude_none=True)

    async def execute_with_context(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        """执行 `with_context` 对应的数据或流程。"""
        payload = WorkerTaskPayload.model_validate(arguments)
        result = await self._worker.run(
            payload,
            parent_run_id=context.run_id,
            conversation_id=context.conversation_id,
        )
        return result.model_dump(mode="json", exclude_none=True)


def planner_system_prompt(base: str | None) -> str:
    """确保 Planner 角色约束只注入一次。"""

    normalized = (base or "").strip()
    if PLANNER_SYSTEM_PROMPT_MARKER in normalized:
        return normalized
    if not normalized:
        return PLANNER_SYSTEM_PROMPT
    return f"{normalized}\n\n{PLANNER_SYSTEM_PROMPT}"


def _non_empty(value: str | None) -> str | None:
    """处理 `_non_empty` 的内部辅助逻辑。"""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _secret_value(value: SecretStr | None) -> str | None:
    """处理 `_secret_value` 的内部辅助逻辑。"""
    if value is None:
        return None
    return _non_empty(value.get_secret_value())


__all__ = [
    "AgentHierarchySettings",
    "DELEGATE_WORKER_TOOL_NAME",
    "DelegateWorkerTool",
    "PLANNER_SYSTEM_PROMPT",
    "WORKER_SYSTEM_PROMPT",
    "WorkerExecutionResult",
    "WorkerSubgraph",
    "WorkerTaskPayload",
    "WORKER_FORBIDDEN_TOOL_NAMES",
    "planner_system_prompt",
]
