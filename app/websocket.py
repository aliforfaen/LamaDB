"""WebSocket endpoint for bidirectional dashboard communication."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.auth import verify_api_key

router = APIRouter()
active_connections: list[WebSocket] = []


@router.websocket("/api/dashboard/ws")
async def dashboard_websocket(websocket: WebSocket):
    """Bidirectional WebSocket for dashboard live refresh.

    Client connects, sends {"key": "<api_key>"} as first message for auth.
    Server verifies the key and keeps the connection open for JSON messages.
    Invalid key → close with code 4001.
    """
    await websocket.accept()
    try:
        msg = await websocket.receive_json()
        key = msg.get("key", "")
        user = await verify_api_key(key)
        if user is None:
            await websocket.close(code=4001, reason="Invalid API key")
            return

        active_connections.append(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                await websocket.send_json({"type": "echo", "data": data})
        except WebSocketDisconnect:
            pass
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)
