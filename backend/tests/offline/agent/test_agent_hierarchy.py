"""单 Runtime Planner -> Worker 子图架构测试。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import SecretStr

from app.agent.hierarchy import (
    DELEGATE_WORKER_TOOL_NAME,
    PLANNER_SYSTEM_PROMPT_MARKER,
    WORKER_SYSTEM_PROMPT,
    AgentHierarchySettings,
    WorkerSubgraph,
)
from app.agent.runtime import AgentRuntime
from app.models.adapter import ModelAdapter
from app.models.config import ModelSettings, ProviderConfig
from app.models.registry import ModelAdapterRegistry
from app.models.types import (
    ApiStyle,
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolDefinition,
)
from app.tools.base import BaseTool
from app.tools.registry import ToolRegistry


class ScriptedAdapter(ModelAdapter):
    def __init__(
        self,
        config: ProviderConfig,
        responses: Sequence[ModelResponse],
    ) -> None:
        super().__init__(config)
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)

    async def close(self) -> None:
        pass


class StubTool(BaseTool):
    def __init__(self, name: str) -> None:
        self._definition = ToolDefinition(name=name)
        self.calls: list[dict[str, Any]] = []

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, arguments: dict[str, Any]) -> str:
        self.calls.append(arguments)
        return "stub-result"


def _response(
    content: str | None = None,
    *,
    tool_calls: tuple[ToolCall, ...] = (),
) -> ModelResponse:
    return ModelResponse(
        id="response",
        provider="fake",
        model="fake-model",
        message=Message(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        ),
    )


def _registry(
    name: str,
    responses: Sequence[ModelResponse],
) -> tuple[ModelAdapterRegistry, ScriptedAdapter]:
    config = ProviderConfig(
        provider=name,
        model=f"{name}-model",
        api_key=SecretStr("test-key"),
        api_style=ApiStyle.CHAT_COMPLETIONS,
    )
    adapter = ScriptedAdapter(config, responses)
    registry = ModelAdapterRegistry(ModelSettings(_env_file=None))
    registry.register(name, lambda _: adapter, config=config)
    return registry, adapter


def test_role_settings_support_independent_provider_credentials() -> None:
    base = ModelSettings(
        _env_file=None,
        model_default_provider=ModelProvider.QWEN,
        qwen_api_key=SecretStr("base-key"),
    )
    hierarchy = AgentHierarchySettings(
        _env_file=None,
        planner_provider=ModelProvider.DEEPSEEK,
        planner_model="planner-model",
        planner_api_key=SecretStr("planner-key"),
        planner_base_url="https://planner.example/v1",
        worker_provider=ModelProvider.DEEPSEEK,
        worker_model="worker-model",
        worker_api_key=SecretStr("worker-key"),
        worker_base_url="https://worker.example/v1",
    )

    planner = hierarchy.planner_model_settings(base)
    worker = hierarchy.worker_model_settings(base, planner=planner)

    assert planner.provider_config("deepseek").model == "planner-model"
    assert planner.provider_config("deepseek").api_key_value() == "planner-key"
    assert worker.provider_config("deepseek").model == "worker-model"
    assert worker.provider_config("deepseek").api_key_value() == "worker-key"


def test_worker_subgraph_rejects_delegate_tool_even_if_registry_contains_it() -> None:
    worker_registry, _ = _registry("worker-fake", [_response("unused")])
    tools = ToolRegistry()
    tools.register(StubTool(DELEGATE_WORKER_TOOL_NAME))

    with pytest.raises(ValueError, match="forbidden tools"):
        WorkerSubgraph(
            model_registry=worker_registry,
            tool_registry=tools,
            provider="worker-fake",
            model="worker-fake-model",
            max_steps=1,
            max_tool_rounds=1,
            max_output_tokens=128,
        )


@pytest.mark.asyncio
async def test_planner_delegates_bounded_task_and_summarizes_worker_result() -> None:
    task_payload = {
        "objective": "读取一个已知文件",
        "instructions": ["读取文件", "返回第一行"],
        "expected_output": "第一行文本",
        "constraints": ["不要修改文件"],
        "context": "文件位置已经由 Planner 确认",
    }
    planner_registry, planner_adapter = _registry(
        "planner-fake",
        [
            _response(
                tool_calls=(
                    ToolCall(
                        id="delegate-1",
                        name=DELEGATE_WORKER_TOOL_NAME,
                        arguments=task_payload,
                    ),
                )
            ),
            _response("Planner 已验收并汇总：worker-result"),
        ],
    )
    worker_registry, worker_adapter = _registry(
        "worker-fake",
        [
            _response(
                tool_calls=(
                    ToolCall(
                        id="worker-write-1",
                        name="write_file",
                        arguments={"path": "result.txt"},
                    ),
                )
            ),
            _response("worker-result"),
        ],
    )
    tools = ToolRegistry()
    read_tool = StubTool("read_file")
    write_tool = StubTool("write_file")
    tools.register(read_tool)
    tools.register(write_tool)
    tools.register(StubTool("task_create"))

    runtime = AgentRuntime(
        planner_registry,
        tools,
        provider="planner-fake",
        worker_model_registry=worker_registry,
        worker_provider="worker-fake",
    )
    result = await runtime.run("处理这个请求")

    assert result.content == "Planner 已验收并汇总：worker-result"
    assert set(runtime.worker_tool_names) == {
        "read_file",
        "write_file",
        "task_create",
    }
    assert DELEGATE_WORKER_TOOL_NAME in tools.names()
    assert DELEGATE_WORKER_TOOL_NAME not in runtime.worker_tool_names
    assert write_tool.calls == [{"path": "result.txt"}]

    planner_request = planner_adapter.requests[0]
    assert PLANNER_SYSTEM_PROMPT_MARKER in (planner_request.messages[0].content or "")
    assert DELEGATE_WORKER_TOOL_NAME in {
        definition.name for definition in planner_request.tools
    }
    assert "write_file" in {definition.name for definition in planner_request.tools}

    first_worker_request = worker_adapter.requests[0]
    assert first_worker_request.messages[0].content == WORKER_SYSTEM_PROMPT
    assert {definition.name for definition in first_worker_request.tools} == {
        "read_file",
        "write_file",
        "task_create",
    }
    assert "读取一个已知文件" in (
        first_worker_request.messages[-1].content or ""
    )
    assert all(
        definition.name != DELEGATE_WORKER_TOOL_NAME
        for request in worker_adapter.requests
        for definition in request.tools
    )

    planner_follow_up = planner_adapter.requests[1]
    worker_result_message = next(
        message
        for message in planner_follow_up.messages
        if message.role is MessageRole.TOOL
        and message.name == DELEGATE_WORKER_TOOL_NAME
    )
    assert "worker-result" in (worker_result_message.content or "")
