# src/models.py
from pydantic import Field, BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from enum import Enum
import json
import uuid

class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    SYSTEM = "system"

class UserStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    AWAY = "away"

# Redis-based models using hash structures and JSON serialization
class ChatMessage(BaseModel):
    """Modelo para mensajes de chat usando Redis"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    dashboard_id: str  # ID del dashboard/pizarra
    user_id: str       # ID del usuario que envía el mensaje
    username: str      # Nombre del usuario (para mostrar)
    content: str = Field(..., max_length=1000)  # Contenido del mensaje
    message_type: MessageType = MessageType.TEXT
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    edited_at: Optional[datetime] = None
    is_deleted: bool = False
    reply_to: Optional[str] = None  # Para responder a mensajes

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el modelo a dict para Redis"""
        data = {
            "id": self.id,
            "dashboard_id": self.dashboard_id,
            "user_id": self.user_id,
            "username": self.username,
            "content": self.content,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp.timestamp(),
            "is_deleted": "1" if self.is_deleted else "0"  # Convertir bool a string
        }
        # Solo agregar campos opcionales si no son None
        if self.edited_at is not None:
            data["edited_at"] = self.edited_at.timestamp()
        if self.reply_to is not None:
            data["reply_to"] = self.reply_to
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        """Crea el modelo desde dict de Redis"""
        # Convertir timestamp a datetime
        if "timestamp" in data and isinstance(data["timestamp"], (int, float)):
            data["timestamp"] = datetime.fromtimestamp(data["timestamp"], tz=timezone.utc)
        if "edited_at" in data and data["edited_at"] and isinstance(data["edited_at"], (int, float)):
            data["edited_at"] = datetime.fromtimestamp(data["edited_at"], tz=timezone.utc)
        # Convertir string a bool
        if "is_deleted" in data:
            data["is_deleted"] = data["is_deleted"] == "1"
        return cls(**data)

    def get_redis_key(self) -> str:
        """Genera la clave Redis para este mensaje"""
        return f"message:{self.dashboard_id}:{self.id}"

class ChatRoom(BaseModel):
    """Modelo para salas de chat usando Redis"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    dashboard_id: str  # Cada dashboard tiene su sala de chat
    name: str          # Nombre de la sala
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str    # Usuario que creó la sala
    is_active: bool = True
    max_users: int = 100  # Límite de usuarios conectados

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el modelo a dict para Redis"""
        data = {
            "id": self.id,
            "dashboard_id": self.dashboard_id,
            "name": self.name,
            "created_at": self.created_at.timestamp(),
            "created_by": self.created_by,
            "is_active": "1" if self.is_active else "0",  # Convertir bool a string
            "max_users": self.max_users
        }
        # Solo agregar descripción si no es None
        if self.description is not None:
            data["description"] = self.description
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatRoom":
        """Crea el modelo desde dict de Redis"""
        if "created_at" in data and isinstance(data["created_at"], (int, float)):
            data["created_at"] = datetime.fromtimestamp(data["created_at"], tz=timezone.utc)
        # Convertir string a bool
        if "is_active" in data:
            data["is_active"] = data["is_active"] == "1"
        return cls(**data)

    def get_redis_key(self) -> str:
        """Genera la clave Redis para esta sala"""
        return f"room:{self.dashboard_id}"

class ConnectedUser(BaseModel):
    """Modelo para usuarios conectados usando Redis"""
    user_id: str
    dashboard_id: str
    username: str
    status: UserStatus = UserStatus.ONLINE
    connected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    socket_id: Optional[str] = None  # ID de la conexión WebSocket

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el modelo a dict para Redis"""
        data = {
            "user_id": self.user_id,
            "dashboard_id": self.dashboard_id, 
            "username": self.username,
            "status": self.status.value,
            "connected_at": self.connected_at.timestamp(),
            "last_seen": self.last_seen.timestamp()
        }
        # Solo agregar socket_id si no es None
        if self.socket_id is not None:
            data["socket_id"] = self.socket_id
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectedUser":
        """Crea el modelo desde dict de Redis"""
        if "connected_at" in data and isinstance(data["connected_at"], (int, float)):
            data["connected_at"] = datetime.fromtimestamp(data["connected_at"], tz=timezone.utc)
        if "last_seen" in data and isinstance(data["last_seen"], (int, float)):
            data["last_seen"] = datetime.fromtimestamp(data["last_seen"], tz=timezone.utc)
        return cls(**data)

    def get_redis_key(self) -> str:
        """Genera la clave Redis para este usuario conectado"""
        return f"user:{self.dashboard_id}:{self.user_id}"

# Modelos para respuestas de API (DTOs)
class MessageResponse(BaseModel):
    id: str
    dashboard_id: str
    user_id: str
    username: str
    content: str
    message_type: MessageType
    timestamp: datetime
    edited_at: Optional[datetime] = None
    is_deleted: bool = False
    reply_to: Optional[str] = None

class UserResponse(BaseModel):
    user_id: str
    username: str
    status: UserStatus
    connected_at: datetime
    last_seen: datetime

class RoomResponse(BaseModel):
    id: str
    dashboard_id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    created_by: str
    is_active: bool
    connected_users: List[UserResponse] = []

# Modelos para requests
class SendMessageRequest(BaseModel):
    content: str = Field(..., max_length=1000)
    message_type: MessageType = MessageType.TEXT
    reply_to: Optional[str] = None

class UpdateMessageRequest(BaseModel):
    content: str = Field(..., max_length=1000)

class CreateRoomRequest(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=500)