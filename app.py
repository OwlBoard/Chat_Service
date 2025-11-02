# app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.database import connect_to_redis, close_redis_connection
from src.routes.chat_routes import router as chat_router
from src.config import settings
from src.logger_config import logger

# Lifespan manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Chat Service...")
    await connect_to_redis()
    logger.info("Chat Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Chat Service...")
    await close_redis_connection()
    logger.info("Chat Service shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="OwlBoard Chat Service",
    description="Real-time chat service for OwlBoard collaborative whiteboard",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat_router)

# Root endpoint
@app.get("/")
async def root():
    return {
        "service": "OwlBoard Chat Service",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "websocket": "/chat/ws/{dashboard_id}?user_id={user_id}&username={username}"
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "chat_service"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )