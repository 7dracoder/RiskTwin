"""Local WebSocket fan-out for the dashboard and the worker page.

Transport only. Nothing here leaves the private LAN, and no model or database port
is exposed to a worker device (spec section 8.4, Mode A).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self._clients:
            return
        async with self._lock:
            targets = list(self._clients)
        stale: list[WebSocket] = []
        for client in targets:
            try:
                await client.send_json(message)
            except Exception:  # noqa: BLE001 - a dropped client must not break the loop
                stale.append(client)
        if stale:
            async with self._lock:
                for client in stale:
                    self._clients.discard(client)
