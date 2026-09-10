"""Agent Runtime 的事件编号与异步流转基础设施。"""

from __future__ import annotations

import asyncio
from typing import Any

from .events import AgentEvent, AgentEventHandler, AgentEventType


class EventEmitter:
    """为单次运行补充公共标识、顺序并隔离处理器异常。"""

    def __init__(
        self,
        *,
        handler: AgentEventHandler,
        run_id: str,
        conversation_id: str | None,
    ) -> None:
        """初始化 `EventEmitter` 实例及其依赖。"""
        self._handler = handler
        self._run_id = run_id
        self._conversation_id = conversation_id
        self._sequence = 0

    async def emit(
        self,
        event_type: AgentEventType,
        **payload: Any,
    ) -> None:
        """发送`EventEmitter`的相关流程。"""
        event = AgentEvent(
            run_id=self._run_id,
            conversation_id=self._conversation_id,
            sequence=self._sequence,
            type=event_type,
            **payload,
        )
        self._sequence += 1
        try:
            await self._handler.emit(event)
        except Exception:
            # 事件观察者故障不能中断 Agent 的核心执行流程。
            return


STREAM_FINISHED = object()


class QueueEventHandler(AgentEventHandler):
    """把 Runtime 回调事件转交给异步迭代器。"""

    def __init__(self) -> None:
        """初始化 `QueueEventHandler` 实例及其依赖。"""
        self._queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue(maxsize=100)

    async def emit(self, event: AgentEvent) -> None:
        """发送`QueueEventHandler`的相关流程。"""
        await self._queue.put(event)

    async def finish(self) -> None:
        """执行 `finish` 对应的业务逻辑。"""
        await self._queue.put(STREAM_FINISHED)

    async def next(self) -> AgentEvent | object:
        """执行 `next` 对应的业务逻辑。"""
        return await self._queue.get()


__all__ = ["EventEmitter", "QueueEventHandler", "STREAM_FINISHED"]
