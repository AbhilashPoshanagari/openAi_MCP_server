from typing import Dict, List, Optional
from fastapi import WebSocket
import json
from datetime import datetime
import asyncio
from collections import defaultdict

class ConnectionManager:
    def __init__(self):
        # room_id -> user_id -> (websocket, user_info)
        self.active_connections: Dict[str, Dict[int, Dict]] = defaultdict(dict)
        # user_id -> room_ids
        self.user_rooms: Dict[int, List[str]] = defaultdict(list)
        # Add inside ConnectionManager.__init__()
        self.user_connections: Dict[int, Dict] = {}

    async def safe_send(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_json(message)
        except Exception:
            pass
    
    async def connect(self, websocket: WebSocket, room_id: str, user_id: int, user_info: dict):
        """Accept WebSocket connection and store it"""
        await websocket.accept()
        
        # Store connection
        self.active_connections[room_id][user_id] = {
            "websocket": websocket,
            "user_info": user_info,
            "connected_at": datetime.now()
        }

        
        # Store global user connection
        self.user_connections[user_id] = {
            "websocket": websocket,
            "user_info": user_info,
            "connected_at": datetime.now()
        }
        
        # Track user's rooms
        if room_id not in self.user_rooms[user_id]:
            self.user_rooms[user_id].append(room_id)
        
        # Notify others in the room
        await self.broadcast_to_room(
            {
                "type": "user-joined",
                "user": user_id,
                "username": user_info.get("username"),
                "timestamp": datetime.now().isoformat()
            },
            room_id,
            exclude_user_id=user_id
        )
        
        # Send current room users to the new user
        room_users = self.get_room_users(room_id)
        await self.send_to_user(
            room_id,
            user_id,
            {
                "type": "room-info",
                "room_id": room_id,
                "users": room_users,
                "timestamp": datetime.now().isoformat()
            }
        )

    
    def disconnect(self, room_id: str, user_id: int):
        """Remove connection from room"""
        if room_id in self.active_connections and user_id in self.active_connections[room_id]:
            del self.active_connections[room_id][user_id]
            
            # Remove empty rooms
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
            
            # Remove room from user's list
            if user_id in self.user_rooms and room_id in self.user_rooms[user_id]:
                self.user_rooms[user_id].remove(room_id)
                if not self.user_rooms[user_id]:
                    del self.user_rooms[user_id]

            if user_id in self.user_connections:
                del self.user_connections[user_id]
    
    async def disconnect_user(self, user_id: int):
        """Disconnect user from all rooms"""
        if user_id in self.user_rooms:
            for room_id in self.user_rooms[user_id].copy():
                self.disconnect(room_id, user_id)
    
    async def send_to_user(self, room_id: str, user_id: int, message: dict):
        """Send message to specific user in a room"""
        if room_id in self.active_connections and user_id in self.active_connections[room_id]:
            try:
                websocket = self.active_connections[room_id][user_id]["websocket"]
                await websocket.send_json(message)
            except Exception as e:
                print(f"Error sending to user {user_id} in room {room_id}: {e}")
                self.disconnect(room_id, user_id)
        elif user_id in self.user_connections:
            # If user is not in the room but has a global connection, send message globally
            await self.send_to_user_global(user_id, message)

    async def send_to_user_global(self, user_id: int, message: dict):
        """Send message to user regardless of room"""
        if user_id not in self.user_connections:
            return

        try:
            websocket = self.user_connections[user_id]["websocket"]
            await websocket.send_json(message)

        except Exception:
            self.user_connections.pop(user_id, None)
    
    async def broadcast_to_room(self, message: dict, room_id: str, exclude_user_id: Optional[int] = None):
        """Broadcast message to all users in a room"""
        if room_id in self.active_connections:
            disconnected_users = []
            
            for user_id, connection_info in self.active_connections[room_id].items():
                if user_id == exclude_user_id:
                    continue
                
                try:
                    await connection_info["websocket"].send_json(message)
                except Exception as e:
                    print(f"Error broadcasting to user {user_id} in room {room_id}: {e}")
                    disconnected_users.append(user_id)
            
            # Clean up disconnected users
            for user_id in disconnected_users:
                self.disconnect(room_id, user_id)
    
    async def send_call_request(self, room_id: str, from_user_id: int, target_username: str, from_username: str):
        """Send call request to specific user"""
        # Find the user ID by username
        target_user_id = None
        for user_id, user_connection in self.user_connections.items():
            connected_username = user_connection.get("user_info", {}).get("username")
            if connected_username == target_username:
                target_user_id = user_id
                break

        if not target_user_id:
            print(f"User {target_username} not found")
            return

        await self.send_to_user(
            room_id,
            target_user_id,
            {
                "type": "call-request",
                "from_user_id": from_user_id,
                "from_username": from_username,
                "room_id": room_id,
                "timestamp": datetime.now().isoformat()
            }
        )
    
    async def send_call_response(self, room_id: str, from_user_id: str, to_user_id: int, from_username: str, accepted: bool):
        """Send call response (accept/reject)"""
        await self.send_to_user_global(
            to_user_id,
            {
                "type": "call-response",
                "from_user_id": from_user_id,
                "from_username": from_username,
                "accepted": accepted,
                "timestamp": datetime.now().isoformat()
            }
        )
    
    async def forward_webrtc_signal(self, room_id: str, from_user_id: int, to_user_id: int, signal_type: str, signal_data: dict):
        """Forward WebRTC signaling messages (offer, answer, ice-candidate)"""
        await self.send_to_user(
            room_id,
            to_user_id,
            {
                "type": signal_type,
                "from_user_id": from_user_id,
                "signal": signal_data,
                "timestamp": datetime.now().isoformat()
            }
        )
    
    def get_room_users(self, room_id: str) -> list:
        """Get list of users in a room"""
        if room_id not in self.active_connections:
            return []
        
        users = []
        for user_id, connection_info in self.active_connections[room_id].items():
            users.append({
                "user_id": user_id,
                "username": connection_info["user_info"].get("username"),
                "connected_at": connection_info["connected_at"].isoformat()
            })
        
        return users
    
    def is_user_in_room(self, room_id: str, user_id: int) -> bool:
        """Check if user is in a room"""
        return (room_id in self.active_connections and 
                user_id in self.active_connections[room_id])
    
    def get_user_rooms(self, user_id: int) -> List[str]:
        """Get all rooms a user is in"""
        return self.user_rooms.get(user_id, [])

# Global connection manager instance
connection_manager = ConnectionManager()