"""
WebSocket connection tracking and broadcast manager.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("videre.backend.websocket")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()    # used to prevent race conditions
    
    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("websocket connected", extra={"connections": len(self._connections)})
    
    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("websocket disconnected", extra={"connections": len(self._connections)})
    
    async def broadcast(self, payload: str) -> int:
        async with self._lock:
            targets = list(self._connections)
        
        delivered = 0
        failed: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_text(payload)
                delivered += 1
            except Exception:
                failed.append(websocket)
        
        if failed:
            async with self._lock:
                for websocket in failed:
                    self._connections.discard(websocket)
            logger.info("dropped unreachable websockets", extra={"count": len(failed)})
        return delivered
    
    @property
    def connection_count(self) -> int:
        return len(self._connections)
