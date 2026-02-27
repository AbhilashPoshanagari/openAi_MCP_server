from starlette.authentication import AuthCredentials, AuthenticationBackend, SimpleUser, BaseUser
from starlette.requests import HTTPConnection
import base64
import binascii

from auth.security import verify_token

class AuthUser(BaseUser):
    def __init__(self, username: str, user_id: int):
        self.username = username
        self.user_id = user_id

    @property
    def is_authenticated(self) -> bool:
        return True

class JWTAuthBackend(AuthenticationBackend):
    """Starlette authentication backend using JWT tokens"""
    
    async def authenticate(self, conn: HTTPConnection):
        # Check for Authorization header
        if "Authorization" not in conn.headers:
            return
        
        auth = conn.headers["Authorization"]
        try:
            # scheme, token = auth.split()
            scheme, _, token = auth.partition(" ")
            if scheme.lower() != 'bearer':
                return
        except ValueError:
            return
        
        # Verify JWT token
        payload = verify_token(token)
        if not payload:
            return
        
        # Get user from database
        from auth.auth_service import auth_service
        user = auth_service.get_user_by_id(payload.get("user_id"))
        
        if not user:
            return
        
        # Return AuthCredentials and User object
        scopes = ["authenticated"]
        if user.is_online:
            scopes.append("online")
        
        # return AuthCredentials(scopes), SimpleUser(user.username)
        return AuthCredentials(scopes), AuthUser(user.username, user.id)