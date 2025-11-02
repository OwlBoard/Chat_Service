# src/config.py
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    redis_url: str = "redis://:password@redis_db:6379/0"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    
    # CORS
    cors_origins: list = ["http://localhost:3000", "http://localhost:3001"]
    
    # Chat settings
    max_message_length: int = 1000
    max_users_per_room: int = 100
    message_history_limit: int = 50
    
    # WebSocket
    websocket_ping_interval: int = 20
    websocket_ping_timeout: int = 10
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()