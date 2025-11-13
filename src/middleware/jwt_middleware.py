# src/middleware/jwt_middleware.py
"""
JWT Authentication Middleware for FastAPI Services

This middleware validates JWT tokens from the centralized Auth Service.
Can be used by User_Service, Canvas_Service, Chat_Service, Comments_Service.

Usage:
    from src.middleware.jwt_middleware import require_auth
    
    @router.get("/protected")
    async def protected_route(current_user: dict = Depends(require_auth)):
        return {"user_id": current_user["user_id"]}
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
import httpx
import os
from functools import lru_cache

# Security scheme for Swagger UI
security = HTTPBearer()

# Auth Service configuration
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "https://auth_service:8443")
CA_CERT_PATH = os.getenv("CA_CERT_PATH", "/etc/ssl/certs/ca.crt")


class TokenValidator:
    """
    Token validator that communicates with Auth Service
    """
    
    def __init__(self):
        self.auth_service_url = AUTH_SERVICE_URL
        self.ca_cert_path = CA_CERT_PATH
        self._client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                verify=self.ca_cert_path if os.path.exists(self.ca_cert_path) else True,
                timeout=httpx.Timeout(5.0)
            )
        return self._client
    
    async def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validate token against Auth Service
        
        Args:
            token: JWT access token
            
        Returns:
            User information dict
            
        Raises:
            HTTPException: If token is invalid or validation fails
        """
        client = await self.get_client()
        
        try:
            response = await client.post(
                f"{self.auth_service_url}/auth/token/validate",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token validation failed",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            data = response.json()
            
            if not data.get("valid"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=data.get("message", "Invalid token"),
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            return {
                "user_id": data.get("user_id"),
                "email": data.get("email"),
                "scopes": data.get("scopes", []),
                "expires_at": data.get("expires_at")
            }
            
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth service timeout"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Auth service unreachable: {str(e)}"
            )
    
    async def close(self):
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()


# Singleton validator instance
_validator = TokenValidator()


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Dependency to require authentication
    
    Usage:
        @router.get("/protected")
        async def protected_route(current_user: dict = Depends(require_auth)):
            return {"user_id": current_user["user_id"]}
    
    Args:
        credentials: HTTP Bearer credentials from request
        
    Returns:
        Dict with user information (user_id, email, scopes, expires_at)
        
    Raises:
        HTTPException 401: If token is invalid or missing
    """
    token = credentials.credentials
    return await _validator.validate_token(token)


async def optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """
    Dependency for optional authentication
    
    Usage:
        @router.get("/public-or-private")
        async def flexible_route(current_user: Optional[dict] = Depends(optional_auth)):
            if current_user:
                return {"message": f"Hello {current_user['email']}"}
            return {"message": "Hello anonymous"}
    
    Args:
        credentials: HTTP Bearer credentials from request (optional)
        
    Returns:
        Dict with user information if token provided and valid, None otherwise
    """
    if credentials is None:
        return None
    
    try:
        return await _validator.validate_token(credentials.credentials)
    except HTTPException:
        return None


def require_scopes(*required_scopes: str):
    """
    Dependency factory to require specific scopes
    
    Usage:
        @router.delete("/admin/users/{user_id}")
        async def delete_user(
            user_id: int,
            current_user: dict = Depends(require_scopes("admin", "write"))
        ):
            return {"message": "User deleted"}
    
    Args:
        *required_scopes: Scopes that user must have
        
    Returns:
        Dependency function that validates scopes
    """
    async def _require_scopes(
        current_user: Dict[str, Any] = Depends(require_auth)
    ) -> Dict[str, Any]:
        user_scopes = set(current_user.get("scopes", []))
        missing_scopes = set(required_scopes) - user_scopes
        
        if missing_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scopes: {', '.join(missing_scopes)}"
            )
        
        return current_user
    
    return _require_scopes


# Cleanup function for app shutdown
async def cleanup_auth_middleware():
    """Call this in FastAPI lifespan shutdown"""
    await _validator.close()
