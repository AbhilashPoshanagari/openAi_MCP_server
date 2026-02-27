from datetime import datetime, timedelta
from typing import Optional, Tuple
from fastapi import HTTPException, status

import config
from postgres.postgres_conn import PostgreSQL
from auth.security import (
    verify_password, 
    get_password_hash, 
    create_access_token, 
    create_refresh_token,
    verify_token,
    refresh_access_token
)
from models.user_models import UserInDB, UserCreate, UserLogin

class AuthService:
    def __init__(self):
        self.db = PostgreSQL(
                    host=config.POSTGRE_SERVER,
                    port=config.POSTGRE_PORT,
                    user=config.POSTGRE_USERNAME,
                    password=config.POSTGRE_PASSWORD,
                    database=config.POSTGRE_DB
                )
    
    def register_user(self, user_data: UserCreate) -> Tuple[UserInDB, str, str]:
        """Register a new user"""
        # Check if user exists
        existing_user = self.db.fetch_one(
            "SELECT * FROM users WHERE username = %s OR email = %s",
            (user_data.username, user_data.email)
        )
        
        if existing_user:
            if existing_user['username'] == user_data.username:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already registered"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )
        
        # Hash password
        hashed_password = get_password_hash(user_data.password)
        
        # Insert new user
        user_id = self.db.insert_and_get_id(
            """
            INSERT INTO users (username, email, password_hash, created_at, is_online)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_data.username, user_data.email, hashed_password, datetime.utcnow(), True)
        )
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )
        
        # Get the created user
        user_dict = self.db.fetch_one(
            "SELECT * FROM users WHERE id = %s",
            (user_id,)
        )
        
        if not user_dict:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User created but not found"
            )
        
        user = UserInDB(**user_dict)
        
        # Create tokens
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id}
        )
        refresh_token = create_refresh_token(
            data={"sub": user.username, "user_id": user.id}
        )
        
        # Store refresh token
        self.db.create_update_insert(
            """
            UPDATE users 
            SET refresh_token = %s, token_expiry = %s 
            WHERE id = %s
            """,
            (refresh_token, datetime.utcnow() + timedelta(days=7), user.id)
        )
        
        return user, access_token, refresh_token
    
    def authenticate_user(self, username: str, password: str) -> Tuple[UserInDB, str, str]:
        """Authenticate user and return tokens"""
        user_dict = self.db.fetch_one(
            "SELECT * FROM users WHERE username = %s",
            (username,)
        )
        
        if not user_dict:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )
        
        user = UserInDB(**user_dict)
        
        if not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )
        
        # Update last login and online status
        self.db.create_update_insert(
            """
            UPDATE users 
            SET last_login = %s, is_online = %s 
            WHERE id = %s
            """,
            (datetime.utcnow(), True, user.id)
        )
        
        # Create new tokens
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id}
        )
        refresh_token = create_refresh_token(
            data={"sub": user.username, "user_id": user.id}
        )
        
        # Store refresh token
        self.db.create_update_insert(
            """
            UPDATE users 
            SET refresh_token = %s, token_expiry = %s 
            WHERE id = %s
            """,
            (refresh_token, datetime.utcnow() + timedelta(days=7), user.id)
        )
        
        return user, access_token, refresh_token
    
    def get_user_by_id(self, user_id: int) -> Optional[UserInDB]:
        """Get user by ID"""
        user_dict = self.db.fetch_one(
            "SELECT * FROM users WHERE id = %s",
            (user_id,)
        )
        
        if user_dict:
            return UserInDB(**user_dict)
        return None
    
    def get_user_by_username(self, username: str) -> Optional[UserInDB]:
        """Get user by username"""
        user_dict = self.db.fetch_one(
            "SELECT * FROM users WHERE username = %s",
            (username,)
        )
        
        if user_dict:
            return UserInDB(**user_dict)
        return None
    
    def update_user_status(self, user_id: int, is_online: bool = None, call_status: str = None) -> bool:
        """Update user status"""
        updates = []
        params = []
        
        if is_online is not None:
            updates.append("is_online = %s")
            params.append(is_online)
        
        if call_status is not None:
            updates.append("call_status = %s")
            params.append(call_status)
        
        if not updates:
            return False
        
        params.append(user_id)
        
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = %s"
        self.db.create_update_insert(query, tuple(params))
        return True
    
    def search_users(self, query: str, current_user_id: int, limit: int = 20) -> list:
        """Search users by username or email"""
        search_pattern = f"%{query}%"
        
        users = self.db.fetch_all(
            """
            SELECT id, username, email, is_online, call_status
            FROM users 
            WHERE (username ILIKE %s OR email ILIKE %s)
            AND id != %s
            AND is_online = true
            ORDER BY username
            LIMIT %s
            """,
            (search_pattern, search_pattern, current_user_id, limit)
        )
        
        return [UserInDB(**user).to_search_dict() for user in users]
    
    def get_online_users(self, current_user_id: int) -> list:
        """Get all online users except current user"""
        users = self.db.fetch_all(
            """
            SELECT id, username, email, is_online, call_status
            FROM users 
            WHERE is_online = true 
            AND id != %s
            ORDER BY username
            """,
            (current_user_id,)
        )
        
        return [UserInDB(**user).to_search_dict() for user in users]
    
    def logout_user(self, user_id: int) -> bool:
        """Logout user by clearing tokens and setting offline"""
        self.db.create_update_insert(
            """
            UPDATE users 
            SET is_online = %s, refresh_token = NULL, token_expiry = NULL
            WHERE id = %s
            """,
            (False, user_id)
        )
        return True
    
    def validate_refresh_token(self, refresh_token: str) -> Optional[UserInDB]:
        """Validate refresh token and return user"""
        user_dict = self.db.fetch_one(
            """
            SELECT * FROM users 
            WHERE refresh_token = %s 
            AND token_expiry > %s
            """,
            (refresh_token, datetime.utcnow())
        )
        
        if user_dict:
            return UserInDB(**user_dict)
        return None

# Create global instance
auth_service = AuthService()