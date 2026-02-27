from starlette.applications import Starlette
from starlette.routing import WebSocketRoute, Route
from starlette.websockets import WebSocket, WebSocketDisconnect
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from typing import Dict

# -------------------------------
# Connection Manager
# -------------------------------
class ConnectionManager:
    def __init__(self):
        # room_id -> { user_id -> WebSocket }
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str):
        await websocket.accept()

        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}

        self.active_connections[room_id][user_id] = websocket
        print(f"User {user_id} connected to room {room_id}")

    def disconnect(self, room_id: str, user_id: str):
        if room_id in self.active_connections:
            self.active_connections[room_id].pop(user_id, None)

            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

        print(f"User {user_id} disconnected from room {room_id}")

    async def send_personal_message(self, message: dict, room_id: str, user_id: str):
        if (
            room_id in self.active_connections
            and user_id in self.active_connections[room_id]
        ):
            await self.active_connections[room_id][user_id].send_json(message)

    async def broadcast(self, message: dict, room_id: str, exclude_user_id: str = None):
        if room_id not in self.active_connections:
            return

        for uid, ws in self.active_connections[room_id].items():
            if uid != exclude_user_id:
                await ws.send_json(message)


manager = ConnectionManager()

# -------------------------------
# WebSocket Endpoint
# -------------------------------
async def websocket_endpoint(websocket: WebSocket):
    # Extract path params manually
    room_id = websocket.path_params["room_id"]
    user_id = websocket.path_params["user_id"]

    await manager.connect(websocket, room_id, user_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "offer":
                await manager.broadcast(
                    {
                        "type": "offer",
                        "offer": data["offer"],
                        "sender": user_id,
                    },
                    room_id,
                    exclude_user_id=user_id,
                )

            elif msg_type == "answer":
                target = data.get("target")
                if target:
                    await manager.send_personal_message(
                        {
                            "type": "answer",
                            "answer": data["answer"],
                            "sender": user_id,
                        },
                        room_id,
                        target,
                    )

            elif msg_type == "ice-candidate":
                target = data.get("target")
                if target:
                    await manager.send_personal_message(
                        {
                            "type": "ice-candidate",
                            "candidate": data["candidate"],
                            "sender": user_id,
                        },
                        room_id,
                        target,
                    )

            elif msg_type == "user-joined":
                await manager.broadcast(
                    {"type": "user-joined", "user": user_id},
                    room_id,
                    exclude_user_id=user_id,
                )

            elif msg_type == "screen-sharing":
                await manager.broadcast(
                    {
                        "type": "screen-sharing",
                        "isSharing": data["isSharing"],
                        "sender": user_id,
                    },
                    room_id,
                    exclude_user_id=user_id,
                )

    except WebSocketDisconnect:
        manager.disconnect(room_id, user_id)
        await manager.broadcast(
            {"type": "user-left", "user": user_id},
            room_id,
        )


# -------------------------------
# HTTP Endpoint (WebRTC Config)
# -------------------------------
async def get_webrtc_config(request):
    return JSONResponse(
        {
            "iceServers": [
                {"urls": "stun:stun.l.google.com:19302"},
                {"urls": "stun:stun1.l.google.com:19302"},
                # TURN example:
                # {
                #   "urls": "turn:your-turn-server.com:3478",
                #   "username": "user",
                #   "credential": "pass"
                # }
            ]
        }
    )


# -------------------------------
# Starlette App
# -------------------------------
routes = [
    WebSocketRoute("/ws/{room_id}/{user_id}", websocket_endpoint),
    Route("/config", get_webrtc_config),
]

app = Starlette(debug=True, routes=routes)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
