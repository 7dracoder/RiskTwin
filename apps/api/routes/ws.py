"""WebSocket feed for the dashboard and the worker page."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_feed(websocket: WebSocket) -> None:
    state = websocket.app.state.risktwin
    await state.bus.connect(websocket)
    try:
        await websocket.send_json({"kind": "hello", "system": await state.system_snapshot()})
        while True:
            # The client does not need to send anything; this keeps the socket open
            # and lets a disconnect surface promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        with contextlib.suppress(Exception):
            await state.bus.disconnect(websocket)
