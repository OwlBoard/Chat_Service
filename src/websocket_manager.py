# src/websocket_manager.py
import json
from typing import Dict, List
from fastapi import WebSocket
from datetime import datetime, timezone
from src.models import ConnectedUser, ChatMessage, UserStatus, MessageType
from src.logger_config import logger
from src.database import get_redis

class ConnectionManager:
    def __init__(self):
        # Dashboard ID -> {user_id: WebSocket}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # WebSocket -> {dashboard_id, user_id, username}
        self.connection_info: Dict[WebSocket, Dict[str, str]] = {}

    async def connect(self, websocket: WebSocket, dashboard_id: str, user_id: str, username: str):
        """Conectar un nuevo usuario al chat"""
        await websocket.accept()
        
        # Initialize dashboard connections if not exists
        if dashboard_id not in self.active_connections:
            self.active_connections[dashboard_id] = {}
        
        # Store connection
        self.active_connections[dashboard_id][user_id] = websocket
        self.connection_info[websocket] = {
            "dashboard_id": dashboard_id,
            "user_id": user_id,
            "username": username
        }
        
        # Save user as connected in Redis
        try:
            redis = await get_redis()
            
            # Create connected user
            connected_user = ConnectedUser(
                user_id=user_id,
                dashboard_id=dashboard_id,
                username=username,
                status=UserStatus.ONLINE,
                socket_id=str(id(websocket))
            )
            
            # Save to Redis
            user_key = connected_user.get_redis_key()
            user_data = connected_user.to_dict()
            logger.info(f"Saving user data to Redis: {user_data}")
            await redis.hset(user_key, mapping=user_data)
            
            # Add to set of connected users for the dashboard
            set_key = f"connected_users:{dashboard_id}"
            await redis.sadd(set_key, user_id)
            
            # Set TTL for cleanup (1 hour)
            await redis.expire(user_key, 60 * 60)
            
            logger.info(f"User {username} connected to dashboard {dashboard_id}")
            
            # Notify other users
            await self.broadcast_user_joined(dashboard_id, username)
            
        except Exception as e:
            logger.error(f"Error saving connected user: {e}")

    async def disconnect(self, websocket: WebSocket):
        """Desconectar usuario del chat"""
        if websocket not in self.connection_info:
            return
        
        connection_data = self.connection_info[websocket]
        dashboard_id = connection_data["dashboard_id"]
        user_id = connection_data["user_id"]
        username = connection_data["username"]
        
        # Remove from active connections
        if dashboard_id in self.active_connections:
            if user_id in self.active_connections[dashboard_id]:
                del self.active_connections[dashboard_id][user_id]
            
            # Remove empty dashboard
            if not self.active_connections[dashboard_id]:
                del self.active_connections[dashboard_id]
        
        del self.connection_info[websocket]
        
        # Update user status in Redis
        try:
            redis = await get_redis()
            
            # Remove from Redis
            user_key = f"user:{dashboard_id}:{user_id}"
            await redis.delete(user_key)
            
            # Remove from set
            set_key = f"connected_users:{dashboard_id}"
            await redis.srem(set_key, user_id)
            
            logger.info(f"User {username} disconnected from dashboard {dashboard_id}")
            
            # Notify other users
            await self.broadcast_user_left(dashboard_id, username)
            
        except Exception as e:
            logger.error(f"Error updating disconnected user: {e}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Enviar mensaje personal a una conexión específica"""
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")

    async def broadcast_to_dashboard(self, dashboard_id: str, message: str, exclude_user_id: str = None):
        """Enviar mensaje a todos los usuarios conectados a un dashboard"""
        if dashboard_id not in self.active_connections:
            return
        
        connections = self.active_connections[dashboard_id]
        disconnected_users = []
        
        for user_id, websocket in connections.items():
            if exclude_user_id and user_id == exclude_user_id:
                continue
                
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.error(f"Error sending message to user {user_id}: {e}")
                disconnected_users.append(websocket)
        
        # Clean up disconnected users
        for websocket in disconnected_users:
            await self.disconnect(websocket)

    async def broadcast_message(self, chat_message: ChatMessage):
        """Broadcast de un mensaje de chat a todos los usuarios del dashboard"""
        try:
            message_data = {
                "type": "chat_message",
                "data": {
                    "id": chat_message.id,
                    "dashboard_id": chat_message.dashboard_id,
                    "user_id": chat_message.user_id,
                    "username": chat_message.username,
                    "content": chat_message.content,
                    "message_type": chat_message.message_type.value,
                    "timestamp": chat_message.timestamp.isoformat()
                }
            }
            if chat_message.reply_to is not None:
                message_data["data"]["reply_to"] = chat_message.reply_to
            
            json_message = json.dumps(message_data)
            
            await self.broadcast_to_dashboard(
                chat_message.dashboard_id,
                json_message
            )
            
        except Exception as e:
            logger.error(f"Error in broadcast_message: {e}")

    async def broadcast_user_joined(self, dashboard_id: str, username: str):
        """Notificar que un usuario se unió al chat"""
        message_data = {
            "type": "user_joined",
            "data": {
                "username": username,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
        await self.broadcast_to_dashboard(dashboard_id, json.dumps(message_data))

    async def broadcast_user_left(self, dashboard_id: str, username: str):
        """Notificar que un usuario salió del chat"""
        message_data = {
            "type": "user_left",
            "data": {
                "username": username,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
        await self.broadcast_to_dashboard(dashboard_id, json.dumps(message_data))

    async def broadcast_typing(self, dashboard_id: str, user_id: str, username: str, is_typing: bool):
        """Broadcast de indicador de escritura"""
        message_data = {
            "type": "typing",
            "data": {
                "user_id": user_id,
                "username": username,
                "is_typing": is_typing,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
        await self.broadcast_to_dashboard(
            dashboard_id,
            json.dumps(message_data),
            exclude_user_id=user_id
        )

    def get_connected_users(self, dashboard_id: str) -> List[str]:
        """Obtener lista de usuarios conectados a un dashboard"""
        if dashboard_id not in self.active_connections:
            return []
        
        return list(self.active_connections[dashboard_id].keys())

    def get_connection_count(self, dashboard_id: str) -> int:
        """Obtener número de usuarios conectados a un dashboard"""
        if dashboard_id not in self.active_connections:
            return 0
        
        return len(self.active_connections[dashboard_id])

# Global instance
connection_manager = ConnectionManager()