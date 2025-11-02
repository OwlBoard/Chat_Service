# src/routes/chat_routes.py
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict, Any
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

# ==================== Redis Helper Functions ====================

async def save_message_to_redis(message: ChatMessage):
    """Guardar mensaje en Redis"""
    redis = await get_redis()
    
    # Guardar el mensaje como hash
    key = message.get_redis_key()
    message_data = message.to_dict()
    logger.info(f"Saving message to Redis: {message_data}")
    await redis.hset(key, mapping=message_data)
    
    # Agregar a la lista de mensajes del dashboard (para historial)
    list_key = f"messages:{message.dashboard_id}"
    await redis.rpush(list_key, message.id)
    
    # Mantener solo los últimos N mensajes (limpieza automática)
    await redis.ltrim(list_key, -settings.message_history_limit, -1)
    
    # Set TTL para el mensaje (opcional, ej: 30 días)
    await redis.expire(key, 30 * 24 * 60 * 60)

async def get_messages_from_redis(dashboard_id: str, limit: int = 50, skip: int = 0) -> List[ChatMessage]:
    """Obtener mensajes desde Redis"""
    redis = await get_redis()
    
    # Obtener IDs de mensajes
    list_key = f"messages:{dashboard_id}"
    message_ids = await redis.lrange(list_key, skip, skip + limit - 1)
    
    messages = []
    for msg_id in message_ids:
        key = f"message:{dashboard_id}:{msg_id}"
        message_data = await redis.hgetall(key)
        if message_data:
            try:
                messages.append(ChatMessage.from_dict(message_data))
            except Exception as e:
                logger.error(f"Error parsing message {msg_id}: {e}")
                continue
    
    return messages

async def save_connected_user_to_redis(user: ConnectedUser):
    """Guardar usuario conectado en Redis"""
    redis = await get_redis()
    
    # Guardar usuario como hash
    key = user.get_redis_key()
    await redis.hset(key, mapping=user.to_dict())
    
    # Agregar a set de usuarios conectados del dashboard
    set_key = f"connected_users:{user.dashboard_id}"
    await redis.sadd(set_key, user.user_id)
    
    # TTL para limpieza automática (ej: 1 hora de inactividad)
    await redis.expire(key, 60 * 60)

async def get_connected_users_from_redis(dashboard_id: str) -> List[ConnectedUser]:
    """Obtener usuarios conectados desde Redis"""
    redis = await get_redis()
    
    # Obtener IDs de usuarios conectados
    set_key = f"connected_users:{dashboard_id}"
    user_ids = await redis.smembers(set_key)
    
    users = []
    for user_id in user_ids:
        key = f"user:{dashboard_id}:{user_id}"
        user_data = await redis.hgetall(key)
        if user_data:
            try:
                users.append(ConnectedUser.from_dict(user_data))
            except Exception as e:
                logger.error(f"Error parsing user {user_id}: {e}")
                continue
    
    return users

async def remove_user_from_redis(dashboard_id: str, user_id: str):
    """Remover usuario de Redis"""
    redis = await get_redis()
    
    # Remover del hash
    key = f"user:{dashboard_id}:{user_id}"
    await redis.delete(key)
    
    # Remover del set
    set_key = f"connected_users:{dashboard_id}"
    await redis.srem(set_key, user_id)

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
        # Validar IDs como strings UUID (opcional)
        if not dashboard_id or not user_id:
            await websocket.close(code=4000, reason="Invalid IDs")
            return
        
        # Connect user
        await connection_manager.connect(websocket, dashboard_id, user_id, username)
        
        # Guardar usuario conectado en Redis
        connected_user = ConnectedUser(
            user_id=user_id,
            dashboard_id=dashboard_id,
            username=username,
            status=UserStatus.ONLINE
        )
        await save_connected_user_to_redis(connected_user)
        
        try:
            while True:
                # Receive message from WebSocket
                data = await websocket.receive_text()
                logger.info(f"Received WebSocket data: {data}")
                
                message_data = json.loads(data)
                logger.info(f"Parsed message data: {message_data}")
                
                # Handle different message types
                if message_data.get("type") == "chat_message":
                    logger.info(f"Processing chat_message type")
                    try:
                        await handle_websocket_message(
                            dashboard_id, user_id, username, 
                            message_data.get("data", {}),
                            websocket
                        )
                        logger.info(f"Message processing completed successfully")
                        
                        # Verificar si la conexión sigue activa después del procesamiento
                        if dashboard_id in connection_manager.active_connections:
                            logger.info(f"Connection still active after message processing")
                        else:
                            logger.warning(f"Connection lost after message processing")
                            
                    except Exception as msg_error:
                        logger.error(f"Error in handle_websocket_message: {msg_error}")
                        import traceback
                        logger.error(f"Traceback: {traceback.format_exc()}")
                elif message_data.get("type") == "typing":
                    logger.info(f"Processing typing type")
                    await connection_manager.broadcast_typing(
                        dashboard_id, user_id, username,
                        message_data.get("data", {}).get("is_typing", False)
                    )
                else:
                    logger.warning(f"Unknown message type: {message_data.get('type')}")
                
                logger.info(f"Message loop iteration completed, continuing...")
                    
        except WebSocketDisconnect:
            await connection_manager.disconnect(websocket)
            await remove_user_from_redis(dashboard_id, user_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await connection_manager.disconnect(websocket)
            await remove_user_from_redis(dashboard_id, user_id)
            
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        await websocket.close()

async def handle_websocket_message(
    dashboard_id: str, 
    user_id: str, 
    username: str, 
    message_data: dict,
    websocket: WebSocket = None
):
    """Manejar mensaje recibido por WebSocket"""
    try:
        # Accept both 'content' and 'message' for backwards compatibility
        content = message_data.get("content") or message_data.get("message", "")
        content = content.strip()
        if not content or len(content) > settings.max_message_length:
            logger.warning(f"Invalid message: empty or too long")
            return
        
        message_type = MessageType(message_data.get("message_type", "text"))
        reply_to = message_data.get("reply_to")
        
        # Create and save message
        chat_message = ChatMessage(
            dashboard_id=dashboard_id,
            user_id=user_id,
            username=username,
            content=content,
            message_type=message_type,
            reply_to=reply_to
        )
        
        await save_message_to_redis(chat_message)
        
        # Broadcast to all connected users
        await connection_manager.broadcast_message(chat_message)
        
    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")

# ==================== REST API Endpoints ====================

@router.get("/messages/{dashboard_id}", response_model=List[MessageResponse])
async def get_messages(
    dashboard_id: str,
    limit: int = Query(default=50, le=100),
    skip: int = Query(default=0, ge=0)
):
    """Obtener historial de mensajes de un dashboard"""
    try:
        messages = await get_messages_from_redis(dashboard_id, limit, skip)
        
        # Convert to response format
        return [
            MessageResponse(
                id=msg.id,
                dashboard_id=msg.dashboard_id,
                user_id=msg.user_id,
                username=msg.username,
                content=msg.content,
                message_type=msg.message_type,
                timestamp=msg.timestamp,
                edited_at=msg.edited_at,
                is_deleted=msg.is_deleted,
                reply_to=msg.reply_to
            )
            for msg in messages
        ]
        
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/messages/{dashboard_id}", response_model=MessageResponse)
async def send_message(
    dashboard_id: str,
    user_id: str,
    username: str,
    content: str,
    message_type: str = "text"
):
    """Enviar mensaje a través de REST API (alternativa a WebSocket)"""
    try:
        # Validate content
        if not content.strip():
            raise HTTPException(status_code=400, detail="Message content cannot be empty")
        
        logger.info("Creating message object...")
        # Create message manually to avoid issues
        try:
            chat_message = ChatMessage(
                dashboard_id=dashboard_id,
                user_id=user_id,
                username=username,
                content=content.strip(),
                message_type=MessageType.TEXT,  # Hardcode por ahora
                reply_to=None  # Hardcode por ahora
            )
            logger.info(f"Created message object: {chat_message.id}")
        except Exception as e:
            logger.error(f"Error creating message object: {e}")
            raise e
        
        try:
            await save_message_to_redis(chat_message)
            logger.info(f"Message saved to Redis successfully")
        except Exception as e:
            logger.error(f"Error saving to Redis: {e}")
            raise e
        
        # Broadcast via WebSocket if users are connected
        await connection_manager.broadcast_message(chat_message)
        
        # Return response
        return MessageResponse(
            id=chat_message.id,
            dashboard_id=chat_message.dashboard_id,
            user_id=chat_message.user_id,
            username=chat_message.username,
            content=chat_message.content,
            message_type=chat_message.message_type,
            timestamp=chat_message.timestamp,
            reply_to=chat_message.reply_to
        )
        
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/rooms/{dashboard_id}", response_model=RoomResponse)
async def get_room_info(dashboard_id: str):
    """Obtener información de la sala de chat"""
    try:
        redis = await get_redis()
        
        # Get or create room info from Redis
        room_key = f"room:{dashboard_id}"
        room_data = await redis.hgetall(room_key)
        
        if not room_data:
            # Create default room
            room = ChatRoom(
                dashboard_id=dashboard_id,
                name=f"Dashboard {dashboard_id}",
                created_by=dashboard_id  # Temporary, should be actual user
            )
            await redis.hset(room_key, mapping=room.to_dict())
        else:
            room = ChatRoom.from_dict(room_data)
        
        # Get connected users
        connected_users = await get_connected_users_from_redis(dashboard_id)
        
        return RoomResponse(
            id=room.id,
            dashboard_id=room.dashboard_id,
            name=room.name,
            description=room.description,
            created_at=room.created_at,
            created_by=room.created_by,
            is_active=room.is_active,
            connected_users=[
                UserResponse(
                    user_id=user.user_id,
                    username=user.username,
                    status=user.status,
                    connected_at=user.connected_at,
                    last_seen=user.last_seen
                )
                for user in connected_users
            ]
        )
        
    except Exception as e:
        logger.error(f"Error getting room info: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/users/{dashboard_id}", response_model=List[UserResponse])
async def get_connected_users(dashboard_id: str):
    """Obtener usuarios conectados a un dashboard"""
    try:
        connected_users = await get_connected_users_from_redis(dashboard_id)
        
        return [
            UserResponse(
                user_id=user.user_id,
                username=user.username,
                status=user.status,
                connected_at=user.connected_at,
                last_seen=user.last_seen
            )
            for user in connected_users
        ]
        
    except Exception as e:
        logger.error(f"Error getting connected users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/messages/{dashboard_id}")
async def clear_all_messages(dashboard_id: str):
    """Eliminar todos los mensajes de un dashboard"""
    try:
        redis = await get_redis()
        
        # Obtener todos los IDs de mensajes del dashboard
        list_key = f"messages:{dashboard_id}"
        message_ids = await redis.lrange(list_key, 0, -1)
        
        # Eliminar cada mensaje individualmente
        deleted_count = 0
        for msg_id in message_ids:
            message_key = f"message:{dashboard_id}:{msg_id}"
            result = await redis.delete(message_key)
            if result:
                deleted_count += 1
        
        # Limpiar la lista de mensajes
        await redis.delete(list_key)
        
        logger.info(f"Cleared {deleted_count} messages from dashboard {dashboard_id}")
        
        # Notificar a todos los usuarios conectados que se limpiaron los mensajes
        await connection_manager.broadcast_to_dashboard(
            dashboard_id,
            json.dumps({
                "type": "messages_cleared",
                "data": {
                    "dashboard_id": dashboard_id,
                    "cleared_count": deleted_count,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            })
        )
        
        return {
            "status": "success",
            "cleared_count": deleted_count,
            "dashboard_id": dashboard_id
        }
        
    except Exception as e:
        logger.error(f"Error clearing messages: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ==================== Health Check ====================

@router.post("/test-message/{dashboard_id}")
async def test_send_message(dashboard_id: str):
    """Endpoint de prueba simple"""
    try:
        # Crear mensaje hardcoded para test
        chat_message = ChatMessage(
            dashboard_id=dashboard_id,
            user_id="test-user",
            username="TestUser",
            content="Test message",
            message_type=MessageType.TEXT,
            reply_to=None
        )
        
        await save_message_to_redis(chat_message)
        return {"status": "success", "message_id": chat_message.id}
    except Exception as e:
        logger.error(f"Test error: {e}")
        return {"status": "error", "error": str(e)}

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        redis = await get_redis()
        await redis.ping()  # Test Redis connection
        
        return {
            "status": "healthy",
            "service": "chat_service",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "redis",
            "active_connections": sum(
                len(connections) for connections in connection_manager.active_connections.values()
            )
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "chat_service",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }