"""Anthropic Messages API 适配器。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import AsyncAnthropic

from ..adapter import ModelAdapter
from ..config import ProviderConfig
from ..errors import ModelAdapterError, UnsupportedMessageError
from ..types import (
    Message,
    MessageRole,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)


class AnthropicAdapter(ModelAdapter):
    def __init__(
        self,
        config: ProviderConfig,
        *,
        client: Any | None = None,
    ) -> None:
        """初始化 `AnthropicAdapter` 实例及其依赖。"""
        super().__init__(config)
        client_kwargs: dict[str, Any] = {
            "api_key": config.api_key_value(),
            "timeout": config.timeout_seconds,
            "max_retries": config.max_retries,
        }
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self._client = client or AsyncAnthropic(**client_kwargs)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """执行 `complete` 对应的业务逻辑。"""
        kwargs = self._request_kwargs(request)

        try:
            response = await self._client.messages.create(**kwargs)
        except Exception as exc:
            raise ModelAdapterError(
                f"{self.provider} model request failed: {exc}"
            ) from exc

        return _normalize_anthropic_response(response, self.provider)

    async def complete_stream(
        self,
        request: ModelRequest,
        *,
        on_text_delta: Callable[[str], Awaitable[None]],
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> ModelResponse:
        """执行 `complete_stream` 对应的业务逻辑。"""
        kwargs = self._request_kwargs(request)
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if text:
                        await on_text_delta(text)
                response = await stream.get_final_message()
        except Exception as exc:
            raise ModelAdapterError(
                f"{self.provider} model stream failed: {exc}"
            ) from exc
        return _normalize_anthropic_response(response, self.provider)

    def _request_kwargs(self, request: ModelRequest) -> dict[str, Any]:
        """请求 `kwargs` 对应的数据或流程。"""
        system, messages = _anthropic_messages(request.messages)
        kwargs: dict[str, Any] = {
            "model": request.model or self.default_model,
            "max_tokens": (
                request.max_output_tokens or self.config.default_max_output_tokens
            ),
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if request.tools:
            kwargs["tools"] = [_anthropic_tool(tool) for tool in request.tools]
        if request.tool_choice is not None:
            kwargs["tool_choice"] = _anthropic_tool_choice(request.tool_choice)
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.extra_body:
            kwargs["extra_body"] = request.extra_body
        return kwargs

    async def close(self) -> None:
        """关闭`AnthropicAdapter`的相关流程。"""
        await self._client.close()


def _anthropic_messages(
    messages: tuple[Message, ...],
) -> tuple[str | None, list[dict[str, Any]]]:
    """处理 `_anthropic_messages` 的内部辅助逻辑。"""
    system_parts: list[str] = []
    result: list[dict[str, Any]] = []

    for message in messages:
        if message.role is MessageRole.SYSTEM:
            if message.content:
                system_parts.append(message.content)
            continue

        if message.role is MessageRole.TOOL:
            if not message.tool_call_id:
                raise UnsupportedMessageError(
                    "Anthropic tool results require tool_call_id."
                )
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content or "",
                        }
                    ],
                }
            )
            continue

        content: str | list[dict[str, Any]]
        if message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": _arguments_dict(call.arguments),
                }
                for call in message.tool_calls
            )
            content = blocks
        else:
            content = message.content or ""

        result.append({"role": message.role.value, "content": content})

    return "\n\n".join(system_parts) or None, result


def _normalize_anthropic_response(response: Any, provider: str) -> ModelResponse:
    """标准化 `anthropic_response` 对应的数据或流程。"""
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(block.text)
        elif block_type == "thinking":
            thinking = getattr(block, "thinking", None)
            if thinking:
                reasoning_parts.append(thinking)
        elif block_type == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                )
            )

    base_input_tokens = int(getattr(response.usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)
    cache_read = _optional_usage_int(response.usage, "cache_read_input_tokens")
    cache_write = _optional_usage_int(
        response.usage,
        "cache_creation_input_tokens",
    )
    cache_reported = cache_read is not None or cache_write is not None
    input_tokens = (
        base_input_tokens + (cache_read or 0) + (cache_write or 0)
        if cache_reported
        else base_input_tokens
    )
    return ModelResponse(
        id=response.id,
        provider=provider,
        model=response.model,
        message=Message(
            role=MessageRole.ASSISTANT,
            content="".join(text_parts) or None,
            tool_calls=tuple(tool_calls),
            reasoning="".join(reasoning_parts) or None,
        ),
        finish_reason=response.stop_reason,
        usage=ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cached_input_tokens=(cache_read or 0) if cache_reported else None,
            uncached_input_tokens=(
                base_input_tokens + (cache_write or 0)
                if cache_reported
                else None
            ),
            cache_read_input_tokens=(cache_read or 0) if cache_reported else None,
            cache_write_input_tokens=cache_write,
            model_calls=1,
        ),
        raw=_model_dump(response),
    )


def _optional_usage_int(usage: Any, field: str) -> int | None:
    """处理 `_optional_usage_int` 的内部辅助逻辑。"""
    value = getattr(usage, field, None)
    if value is None:
        return None
    return max(0, int(value))


def _arguments_dict(arguments: dict[str, Any] | str) -> dict[str, Any]:
    """处理 `_arguments_dict` 的内部辅助逻辑。"""
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise UnsupportedMessageError(
            "Anthropic tool arguments must be a JSON object."
        ) from exc
    if not isinstance(parsed, dict):
        raise UnsupportedMessageError("Anthropic tool arguments must be a JSON object.")
    return parsed


def _anthropic_tool(tool: ToolDefinition) -> dict[str, Any]:
    """处理 `_anthropic_tool` 的内部辅助逻辑。"""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }


def _anthropic_tool_choice(tool_choice: str) -> dict[str, Any]:
    """处理 `_anthropic_tool_choice` 的内部辅助逻辑。"""
    if tool_choice in {"auto", "none", "any"}:
        normalized = "any" if tool_choice == "required" else tool_choice
        return {"type": normalized}
    if tool_choice == "required":
        return {"type": "any"}
    return {"type": "tool", "name": tool_choice}


def _model_dump(value: Any) -> dict[str, Any] | None:
    """处理 `_model_dump` 的内部辅助逻辑。"""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value if isinstance(value, dict) else None
