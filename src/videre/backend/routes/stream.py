"""
WebSocket stream of cluster-health snapshots.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from ..cache.store import read_all_snapshots
from ..websocket.limits import release, try_acquire
from ..websocket.manager import SEND_TIMEOUT_SECONDS

logger = logging.getLogger("videre.backend.stream")

router = APIRouter(tags=["stream"])

RATE_LIMITED_CLOSE_CODE = 1013
UNKNOWN_CLIENT_IP = "unknown"


async def current_payload(redis_client: Redis) -> str:
    snapshots = await read_all_snapshots(redis_client)
    return json.dumps([json.loads(snapshot.model_dump_json()) for snapshot in snapshots])


@router.websocket("/ws/cluster-health")
async def cluster_health_stream(websocket: WebSocket) -> None:
    redis_client = websocket.app.state.redis_client
    manager = websocket.app.state.connection_manager
    settings = websocket.app.state.settings
    client_ip = websocket.client.host if websocket.client else UNKNOWN_CLIENT_IP
    
    if not await try_acquire(redis_client, client_ip, settings.websocket_maximum_connections_per_client):
        await websocket.accept()    # accept before closing so the client receives close code 1013
        await websocket.close(code=RATE_LIMITED_CLOSE_CODE)
        logger.warning("websocket refused: per-client cap reached", extra={"client_ip": client_ip})
        return
    
    async def receive() -> None:
        while True:    # keep the connection open until the client disconnects
            await websocket.receive_text()

    tasks: list[asyncio.Task[None] | asyncio.Task[bool]] = []
    try:
        disconnected = await manager.connect(websocket)
        await manager.send(websocket, await current_payload(redis_client))
        tasks = [asyncio.create_task(receive()), asyncio.create_task(disconnected.wait())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if disconnected.is_set():
            await asyncio.wait_for(websocket.close(code=1011), timeout=SEND_TIMEOUT_SECONDS)
    except WebSocketDisconnect:
        logger.info("websocket client disconnected", extra={"client_ip": client_ip})
    except asyncio.CancelledError:
        logger.info("websocket stream stopped", extra={"client_ip": client_ip})
        raise
    except Exception as error:
        logger.warning("websocket failed", extra={"client_ip": client_ip, "error": str(error)})
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await manager.disconnect(websocket)
        await release(redis_client, client_ip)
