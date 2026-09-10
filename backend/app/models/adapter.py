"""模型适配器的抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from .config import ProviderConfig
from .types import ModelRequest, ModelResponse


class ModelAdapter(ABC):
    def __init__(self, config: ProviderConfig) -> None:
        """初始化 `ModelAdapter` 实例及其依赖。"""
        self.config = config

    @property
    def provider(self) -> str:
        """执行 `provider` 对应的业务逻辑。"""
        return self.config.provider

    @property
    def default_model(self) -> str:
        """执行 `default_model` 对应的业务逻辑。"""
        return self.config.model

    @abstractmethod
    async def complete(self, request: ModelRequest) -> ModelResponse:
        """返回一次统一格式的模型响应。"""

    async def complete_stream(
        self,
        request: ModelRequest,
        *,
        on_text_delta: Callable[[str], Awaitable[None]],
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> ModelResponse:
        """流式返回文本增量，并最终给出完整统一响应。

        自定义 / 测试 Adapter 无需立即实现流式协议；默认路径保持原有
        ``complete`` 行为，但不会伪造文本增量。
        """

        return await self.complete(request)

    @abstractmethod
    async def close(self) -> None:
        """释放模型提供商客户端资源。"""
