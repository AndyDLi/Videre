"""
WebSocket connection tracking and broadcast manager.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("videre.backend.websocket")

SEND_TIMEOUT_SECONDS = 2.0


class ConnectionManager:
    def __init__(self, send_timeout_seconds: float = SEND_TIMEOUT_SECONDS) -> None:
        self._connections: dict[WebSocket, asyncio.Event] = {}
        self._pending: dict[WebSocket, asyncio.Task[bool]] = {}
        self._send_timeout_seconds = send_timeout_seconds
        self._lock = asyncio.Lock()    # used to prevent race conditions

    async def connect(self, websocket: WebSocket) -> asyncio.Event:
        await websocket.accept()
        disconnected = asyncio.Event()
        async with self._lock:
            self._connections[websocket] = disconnected
        logger.info("websocket connected", extra={"connections": len(self._connections)})
        return disconnected

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            disconnected = self._connections.pop(websocket, None)
            if disconnected is not None:
                disconnected.set()
        task = self._pending.get(websocket)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._pending.pop(websocket, None)
        logger.info("websocket disconnected", extra={"connections": len(self._connections)})

    async def _send(self, websocket: WebSocket, payload: str) -> bool:
        try:
            await websocket.send_text(payload)
            return True
        except Exception as error:
            logger.info("dropped unreachable websockets", extra={"count": 1, "error": str(error)})
            await self.disconnect(websocket)
            return False
        finally:
            self._pending.pop(websocket, None)

    def _start_send(self, websocket: WebSocket, payload: str) -> asyncio.Task[bool] | None:
        if websocket not in self._connections or websocket in self._pending:
            return None
        task = asyncio.create_task(self._send(websocket, payload))
        self._pending[websocket] = task
        return task

    async def _wait_for_sends(self, tasks: list[asyncio.Task[bool]]) -> int:
        if not tasks:
            return 0
        done, pending = await asyncio.wait(tasks, timeout=self._send_timeout_seconds)
        if pending:
            # Leave the send owned by its connection; later refreshes skip it until it finishes.
            logger.warning("websocket send timed out; skipping busy clients", extra={"count": len(pending)})
        return sum(task.result() for task in done if not task.cancelled())

    async def send(self, websocket: WebSocket, payload: str) -> bool:
        task = self._start_send(websocket, payload)
        return bool(await self._wait_for_sends([task] if task is not None else []))

    async def broadcast(self, payload: str) -> int:
        async with self._lock:
            targets = list(self._connections)
        tasks = [
            task for websocket in targets
            if (task := self._start_send(websocket, payload)) is not None
        ]
        return await self._wait_for_sends(tasks)

    async def shutdown(self) -> None:
        await asyncio.gather(*(
            self.disconnect(websocket) for websocket in set(self._connections) | set(self._pending)
        ))

    @property
    def connection_count(self) -> int:
        return len(self._connections)
