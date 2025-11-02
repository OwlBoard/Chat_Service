# Chat Service

Real-time chat service for OwlBoard collaborative whiteboard platform.

## 🚀 Features

- **Real-time messaging** via WebSockets
- **Message persistence** in MongoDB
- **Room-based chat** organized by dashboard
- **User presence tracking** (online/offline status)
- **Message history** with pagination
- **Message editing and deletion**
- **Typing indicators**
- **Reply to messages**
- **REST API** for integration

## 🛠️ Technology Stack

- **FastAPI** - Web framework with WebSocket support
- **MongoDB** - Document database for message storage
- **Beanie** - Async ODM for MongoDB
- **WebSockets** - Real-time communication
- **Pydantic** - Data validation and serialization

## 📚 API Endpoints

### WebSocket
- `ws://localhost:8002/chat/ws/{dashboard_id}?user_id={user_id}&username={username}` - Real-time chat connection

### REST API

#### Messages
- `GET /chat/messages/{dashboard_id}` - Get message history
- `POST /chat/messages/{dashboard_id}` - Send message via REST
- `PUT /chat/messages/{message_id}` - Edit message
- `DELETE /chat/messages/{message_id}` - Delete message

#### Rooms
- `GET /chat/rooms/{dashboard_id}` - Get room information
- `GET /chat/users/{dashboard_id}` - Get connected users

#### Health
- `GET /health` - Service health check
- `GET /chat/health` - Chat-specific health check

## 🐳 Docker Setup

### Standalone
```bash
cd Chat_Service
docker-compose up -d
```

### With full OwlBoard stack
```bash
# From root directory
docker-compose up -d
```

The service will be available at:
- **REST API**: http://localhost:8002
- **WebSocket**: ws://localhost:8002/chat/ws/
- **Documentation**: http://localhost:8002/docs

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `mongodb://user:password@mongo_db:27017/chat_db?authSource=admin` | MongoDB connection string |
| `CORS_ORIGINS` | `["http://localhost:3000", "http://localhost:3001"]` | Allowed CORS origins |
| `MAX_MESSAGE_LENGTH` | `1000` | Maximum message length |
| `MAX_USERS_PER_ROOM` | `100` | Maximum users per room |
| `MESSAGE_HISTORY_LIMIT` | `50` | Default message history limit |

## 📱 WebSocket Message Format

### Client to Server

#### Send Message
```json
{
  "type": "chat_message",
  "data": {
    "content": "Hello, world!",
    "message_type": "text",
    "reply_to": "optional_message_id"
  }
}
```

#### Typing Indicator
```json
{
  "type": "typing",
  "data": {
    "is_typing": true
  }
}
```

### Server to Client

#### New Message
```json
{
  "type": "chat_message",
  "data": {
    "id": "message_id",
    "dashboard_id": "dashboard_id",
    "user_id": "user_id",
    "username": "username",
    "content": "Hello, world!",
    "message_type": "text",
    "timestamp": "2025-01-01T12:00:00Z",
    "reply_to": null
  }
}
```

#### User Events
```json
{
  "type": "user_joined",
  "data": {
    "username": "new_user",
    "timestamp": "2025-01-01T12:00:00Z"
  }
}
```

#### Typing Events
```json
{
  "type": "typing",
  "data": {
    "user_id": "user_id",
    "username": "username",
    "is_typing": true,
    "timestamp": "2025-01-01T12:00:00Z"
  }
}
```

## 🧪 Testing

Run tests with pytest:
```bash
pip install -r requirements.txt
pytest
```

## 🏗️ Architecture

```
Chat_Service/
├── app.py                 # FastAPI application
├── src/
│   ├── models.py         # Database models
│   ├── database.py       # Database connection
│   ├── config.py         # Configuration
│   ├── logger_config.py  # Logging setup
│   ├── websocket_manager.py  # WebSocket connection management
│   └── routes/
│       └── chat_routes.py    # API routes
├── tests/                # Unit tests
├── Dockerfile           # Container configuration
├── docker-compose.yml   # Local development setup
└── requirements.txt     # Python dependencies
```

## 🔗 Integration with Frontend

The chat service integrates with the existing OwlBoard frontend through:

1. **Environment variable**: `REACT_APP_CHAT_SERVICE_URL=http://localhost:8002`
2. **WebSocket connection** in the ChatPanel component
3. **REST API calls** for message history and user management

## 📊 Database Schema

### ChatMessage
- `dashboard_id`: Reference to whiteboard
- `user_id`: Message author
- `username`: Display name
- `content`: Message text
- `message_type`: text/image/file/system
- `timestamp`: Created date
- `edited_at`: Last edit date
- `is_deleted`: Soft delete flag
- `reply_to`: Reference to replied message

### ChatRoom
- `dashboard_id`: Associated whiteboard
- `name`: Room display name
- `description`: Room description
- `created_at`: Created date
- `created_by`: Room creator
- `is_active`: Room status

### ConnectedUser
- `user_id`: User reference
- `dashboard_id`: Room reference
- `username`: Display name
- `status`: online/offline/away
- `connected_at`: Connection start
- `last_seen`: Last activity
- `socket_id`: WebSocket connection ID

## 🚧 Future Enhancements

- [ ] File/image sharing
- [ ] Message reactions/emojis
- [ ] Direct messages between users
- [ ] Message search functionality
- [ ] Rate limiting for messages
- [ ] Message encryption
- [ ] Push notifications
- [ ] Voice/video chat integration