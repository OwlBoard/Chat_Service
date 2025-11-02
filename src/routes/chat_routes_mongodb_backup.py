# src/routes/chat_routes.py
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from typing import List, Optional
from datetime import datetime, timezone
import uuid

from src.models import (
    ChatMessage, ChatRoom, ConnectedUser, 
    MessageResponse, UserResponse, RoomResponse,
    SendMessageRequest, UpdateMessageRequest, CreateRoomRequest,
    MessageType, UserStatus
)
from src.websocket_manager import connection_manager
from src.config import settings
from src.logger_config import logger
from src.database import get_redis

router = APIRouter(prefix="/chat", tags=["Chat"])

# ==================== WebSocket Endpoints ====================

@router.websocket("/ws/{dashboard_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    dashboard_id: str,
    user_id: str = Query(...),
    username: str = Query(...)
):
    """WebSocket endpoint para chat en tiempo real"""
    try:
        # Validate ObjectIds
        dashboard_obj_id = PydanticObjectId(dashboard_id)
        user_obj_id = PydanticObjectId(user_id)
        
        # Connect user
        await connection_manager.connect(websocket, dashboard_id, user_id, username)
        
        try:
            while True:
                # Receive message from WebSocket
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # Handle different message types
                if message_data.get("type") == "chat_message":
                    await handle_websocket_message(
                        dashboard_obj_id, user_obj_id, username, 
                        message_data.get("data", {})
                    )
                elif message_data.get("type") == "typing":
                    await connection_manager.broadcast_typing(
                        dashboard_id, user_id, username,
                        message_data.get("data", {}).get("is_typing", False)
                    )
                    
        except WebSocketDisconnect:
            await connection_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await connection_manager.disconnect(websocket)
            
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        await websocket.close()

async def handle_websocket_message(
    dashboard_id: PydanticObjectId, 
    user_id: PydanticObjectId, 
    username: str, 
    message_data: dict
):
    """Manejar mensaje recibido por WebSocket"""
    try:
        content = message_data.get("content", "").strip()
        if not content or len(content) > settings.max_message_length:
            return
        
        message_type = MessageType(message_data.get("message_type", "text"))
        reply_to = message_data.get("reply_to")
        reply_to_obj = PydanticObjectId(reply_to) if reply_to else None
        
        # Create and save message
        chat_message = ChatMessage(
            dashboard_id=dashboard_id,
            user_id=user_id,
            username=username,
            content=content,
            message_type=message_type,
            reply_to=reply_to_obj
        )
        
        await chat_message.insert()
        
        # Broadcast to all connected users
        await connection_manager.broadcast_message(chat_message)
        
        logger.info(f"Message sent by {username} in dashboard {dashboard_id}")
        
    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")

# ==================== REST API Endpoints ====================

@router.get("/messages/{dashboard_id}", response_model=List[MessageResponse])
async def get_messages(
    dashboard_id: str,
    limit: int = Query(default=50, le=100),
    skip: int = Query(default=0, ge=0),
    before: Optional[str] = Query(default=None)
):
    """Obtener historial de mensajes de un dashboard"""
    try:
        dashboard_obj_id = PydanticObjectId(dashboard_id)
        
        # Build query
        query = ChatMessage.find(
            ChatMessage.dashboard_id == dashboard_obj_id,
            ChatMessage.is_deleted == False
        )
        
        # Add timestamp filter if before is provided
        if before:
            before_date = datetime.fromisoformat(before.replace('Z', '+00:00'))
            query = query.find(ChatMessage.timestamp < before_date)
        
        # Execute query with pagination
        messages = await query.sort(-ChatMessage.timestamp).skip(skip).limit(limit).to_list()
        
        # Convert to response format
        return [
            MessageResponse(
                id=str(msg.id),
                dashboard_id=str(msg.dashboard_id),
                user_id=str(msg.user_id),
                username=msg.username,
                content=msg.content,
                message_type=msg.message_type,
                timestamp=msg.timestamp,
                edited_at=msg.edited_at,
                is_deleted=msg.is_deleted,
                reply_to=str(msg.reply_to) if msg.reply_to else None
            )
            for msg in reversed(messages)  # Reverse to get chronological order
        ]
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dashboard ID")
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/messages/{dashboard_id}", response_model=MessageResponse)
async def send_message(
    dashboard_id: str,
    user_id: str,
    username: str,
    message_request: SendMessageRequest
):
    """Enviar mensaje a través de REST API (alternativa a WebSocket)"""
    try:
        dashboard_obj_id = PydanticObjectId(dashboard_id)
        user_obj_id = PydanticObjectId(user_id)
        
        # Validate content
        if not message_request.content.strip():
            raise HTTPException(status_code=400, detail="Message content cannot be empty")
        
        reply_to_obj = None
        if message_request.reply_to:
            reply_to_obj = PydanticObjectId(message_request.reply_to)
        
        # Create message
        chat_message = ChatMessage(
            dashboard_id=dashboard_obj_id,
            user_id=user_obj_id,
            username=username,
            content=message_request.content.strip(),
            message_type=message_request.message_type,
            reply_to=reply_to_obj
        )
        
        await chat_message.insert()
        
        # Broadcast via WebSocket if users are connected
        await connection_manager.broadcast_message(chat_message)
        
        # Return response
        return MessageResponse(
            id=str(chat_message.id),
            dashboard_id=str(chat_message.dashboard_id),
            user_id=str(chat_message.user_id),
            username=chat_message.username,
            content=chat_message.content,
            message_type=chat_message.message_type,
            timestamp=chat_message.timestamp,
            reply_to=str(chat_message.reply_to) if chat_message.reply_to else None
        )
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/messages/{message_id}", response_model=MessageResponse)
async def update_message(
    message_id: str,
    user_id: str,
    update_request: UpdateMessageRequest
):
    """Actualizar mensaje (solo el autor puede editarlo)"""
    try:
        message_obj_id = PydanticObjectId(message_id)
        user_obj_id = PydanticObjectId(user_id)
        
        # Find message
        message = await ChatMessage.get(message_obj_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Check if user is the author
        if message.user_id != user_obj_id:
            raise HTTPException(status_code=403, detail="You can only edit your own messages")
        
        # Update message
        message.content = update_request.content.strip()
        message.edited_at = datetime.now(timezone.utc)
        await message.save()
        
        return MessageResponse(
            id=str(message.id),
            dashboard_id=str(message.dashboard_id),
            user_id=str(message.user_id),
            username=message.username,
            content=message.content,
            message_type=message.message_type,
            timestamp=message.timestamp,
            edited_at=message.edited_at,
            reply_to=str(message.reply_to) if message.reply_to else None
        )
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error updating message: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: str,
    user_id: str
):
    """Eliminar mensaje (soft delete)"""
    try:
        message_obj_id = PydanticObjectId(message_id)
        user_obj_id = PydanticObjectId(user_id)
        
        # Find message
        message = await ChatMessage.get(message_obj_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Check if user is the author
        if message.user_id != user_obj_id:
            raise HTTPException(status_code=403, detail="You can only delete your own messages")
        
        # Soft delete
        message.is_deleted = True
        message.content = "[Message deleted]"
        await message.save()
        
        return {"message": "Message deleted successfully"}
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/rooms/{dashboard_id}", response_model=RoomResponse)
async def get_room_info(dashboard_id: str):
    """Obtener información de la sala de chat"""
    try:
        dashboard_obj_id = PydanticObjectId(dashboard_id)
        
        # Get or create room
        room = await ChatRoom.find_one(ChatRoom.dashboard_id == dashboard_obj_id)
        if not room:
            # Create default room
            room = ChatRoom(
                dashboard_id=dashboard_obj_id,
                name=f"Dashboard {dashboard_id}",
                created_by=dashboard_obj_id  # Temporary, should be actual user
            )
            await room.insert()
        
        # Get connected users
        connected_users = await ConnectedUser.find(
            ConnectedUser.dashboard_id == dashboard_obj_id,
            ConnectedUser.status == UserStatus.ONLINE
        ).to_list()
        
        return RoomResponse(
            id=str(room.id),
            dashboard_id=str(room.dashboard_id),
            name=room.name,
            description=room.description,
            created_at=room.created_at,
            created_by=str(room.created_by),
            is_active=room.is_active,
            connected_users=[
                UserResponse(
                    user_id=str(user.user_id),
                    username=user.username,
                    status=user.status,
                    connected_at=user.connected_at,
                    last_seen=user.last_seen
                )
                for user in connected_users
            ]
        )
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dashboard ID")
    except Exception as e:
        logger.error(f"Error getting room info: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/users/{dashboard_id}", response_model=List[UserResponse])
async def get_connected_users(dashboard_id: str):
    """Obtener usuarios conectados a un dashboard"""
    try:
        dashboard_obj_id = PydanticObjectId(dashboard_id)
        
        connected_users = await ConnectedUser.find(
            ConnectedUser.dashboard_id == dashboard_obj_id,
            ConnectedUser.status == UserStatus.ONLINE
        ).to_list()
        
        return [
            UserResponse(
                user_id=str(user.user_id),
                username=user.username,
                status=user.status,
                connected_at=user.connected_at,
                last_seen=user.last_seen
            )
            for user in connected_users
        ]
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dashboard ID")
    except Exception as e:
        logger.error(f"Error getting connected users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ==================== Health Check ====================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "chat_service",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_connections": sum(
            len(connections) for connections in connection_manager.active_connections.values()
        )
    }