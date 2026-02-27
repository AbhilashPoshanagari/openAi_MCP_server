from pydantic import BaseModel, EmailStr, field_validator, validator
from typing import Optional
from datetime import datetime

# Request models
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    
    @field_validator('username')
    def username_alphanumeric(cls, v):
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('Username must be alphanumeric (underscores and dashes allowed)')
        if len(v) < 3:
            raise ValueError('Username must be at least 3 characters')
        if len(v) > 50:
            raise ValueError('Username must be less than 50 characters')
        return v
    
    @field_validator('password')
    def password_length(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v

class UserLogin(BaseModel):
    username: str
    password: str

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    call_status: Optional[str] = None

class TokenRefresh(BaseModel):
    refresh_token: str

# Response models
class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_online: bool
    call_status: str
    last_login: Optional[str]
    created_at: Optional[str]
    
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse

class UserSearchResponse(BaseModel):
    id: int
    username: str
    email: str
    is_online: bool
    call_status: str

class OnlineUsersResponse(BaseModel):
    users: list[UserSearchResponse]
    total: int

# Database models (not Pydantic)
class UserInDB:
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.username = kwargs.get('username')
        self.email = kwargs.get('email')
        self.password_hash = kwargs.get('password_hash')
        self.created_at = kwargs.get('created_at')
        self.last_login = kwargs.get('last_login')
        self.is_online = kwargs.get('is_online', False)
        self.call_status = kwargs.get('call_status', 'available')
        self.refresh_token = kwargs.get('refresh_token')
        self.token_expiry = kwargs.get('token_expiry')
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON response"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_online": bool(self.is_online),
            "call_status": self.call_status,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
    
    def to_search_dict(self) -> dict:
        """Convert to dictionary for search results"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_online": bool(self.is_online),
            "call_status": self.call_status
        }