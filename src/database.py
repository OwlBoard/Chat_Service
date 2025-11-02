# src/database.py
import os
import redis.asyncio as redis
from src.logger_config import logger
from src.config import settings

class Database:
    client: redis.Redis = None
    
database = Database()

async def connect_to_redis():
    """Create Redis connection"""
    try:
        database.client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            socket_keepalive_options={},
            health_check_interval=30
        )
        
        # Test connection
        await database.client.ping()
        
        logger.info("Connected to Redis successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise

async def close_redis_connection():
    """Close Redis connection"""
    if database.client:
        await database.client.close()
        logger.info("Disconnected from Redis")

async def get_redis():
    """Get Redis instance"""
    if database.client is None:
        await connect_to_redis()
    return database.client