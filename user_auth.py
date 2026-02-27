from fastapi import Depends, HTTPException, WebSocketDisconnect, status
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.authentication import requires
from mediaServices.websocket_service import connection_manager
from models.user_models import TokenRefresh, TokenResponse, UserLogin, UserResponse
from auth.auth_service import auth_service
from auth.security import refresh_access_token, verify_token
from starlette.authentication import AuthCredentials, SimpleUser

# Remove FastAPI dependencies and use Starlette's request object
@requires(["authenticated"])
async def get_me(request: Request):
    """Get current user info - now uses request.user"""
    if not request.user.is_authenticated:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    
    # Get user from database using username
    from auth.auth_service import auth_service
    user = auth_service.get_user_by_username(request.user.display_name)
    
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    
    return JSONResponse(user.to_dict())

# Protected endpoints using @requires decorator
@requires(["authenticated"])
async def update_user_status(request: Request):
    """Update user status - requires authentication"""
    try:
        data = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    
    current_user = request.user
    from auth.auth_service import auth_service
    
    # Get user from database
    # user = auth_service.get_user_by_username(current_user.display_name)
    # if not user:
    #     return JSONResponse({"error": "User not found"}, status_code=404)
    
    # Update status
    is_online = data.get("is_online")
    call_status = data.get("call_status")

    success = auth_service.update_user_status(current_user.user_id, is_online, call_status)

    if success:
        return JSONResponse({"message": "Status updated successfully"})
    else:
        return JSONResponse({"error": "Failed to update status"}, status_code=400)

# Registration endpoint (no authentication required)
async def register(request: Request):
    """Register a new user"""
    try:
        data = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    
    from auth.auth_service import auth_service
    from models.user_models import UserCreate
    
    try:
        user_data = UserCreate(**data)
        user, access_token, refresh_token = auth_service.register_user(user_data)
        
        return JSONResponse({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user.to_dict()
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

async def login(user_data: Request):
    """Login user"""
    try:
        data = await user_data.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    
    user, access_token, refresh_token = auth_service.authenticate_user(
        data["username"], 
        data["password"]
    )
    
    # return TokenResponse(
    #     access_token=access_token,
    #     refresh_token=refresh_token,
    #     user=UserResponse(**user.to_dict())
    # )
    return JSONResponse({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user.to_dict()
    })

async def refresh_token(token_data: TokenRefresh):
    """Refresh access token"""
    user = auth_service.validate_refresh_token(token_data.refresh_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Create new tokens
    new_access_token, new_refresh_token = refresh_access_token(token_data.refresh_token)
    
    if not new_access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not refresh token"
        )
    
    # Update refresh token in database
    if new_refresh_token:
        auth_service.db.create_update_insert(
            """
            UPDATE users 
            SET refresh_token = %s, token_expiry = %s 
            WHERE id = %s
            """,
            (new_refresh_token, None, user.id)  # token_expiry would need to be calculated
        )
    
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token or token_data.refresh_token,
        user=UserResponse(**user.to_dict())
    )

# async def logout(current_user: dict = Depends(verify_token)):
#     """Logout user"""
#     auth_service.logout_user(current_user.user.user_id)
#     return {"message": "Logged out successfully"}

async def logout(request: Request):
    user = request.user

    if not user or not user.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = user.username   # from Starlette User object

    userDetails = auth_service.get_user_by_username(username)
    if not userDetails:
        raise HTTPException(status_code=404, detail="User not found")

    auth_service.logout_user(userDetails.id)

    return JSONResponse({"message": "Logged out successfully"})

async def user_details(request: Request):
    username = request.path_params["username"]
    userDetails = auth_service.get_user_by_username(username)
    if not userDetails:
        raise HTTPException(status_code=404, detail="User not found")

    return JSONResponse({"data": userDetails.to_dict()})

   
async def websocket_endpoint(websocket: Request):
    """WebSocket endpoint for real-time communication"""
    room_id = websocket.path_params["room_id"]

    # 🔹 1. Extract token from query param
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)  # Policy violation
        return

    # 🔹 2. Verify JWT token
    payload = verify_token(token)
    if not payload:
        await websocket.close(code=1008)
        return

    # 🔹 3. Fetch user from DB
    from auth.auth_service import auth_service
    user = auth_service.get_user_by_id(payload.get("user_id"))
    if not user:
        await websocket.close(code=1008)
        return

    # 🔹 4. Attach user to websocket (Starlette way)
    websocket.scope["auth"] = AuthCredentials(["authenticated"])
    websocket.scope["user"] = SimpleUser(user.username)

    # 🔹 5. Accept connection AFTER auth
    # await websocket.accept()

    user_id = user.id
    username = user.username

    # Mark user online
    auth_service.update_user_status(user_id, is_online=True)
    
    # Rest of your WebSocket logic remains the same...
    # Connect to connection_manager
    await connection_manager.connect(
        websocket,
        room_id,
        user_id,
        {"username": username, "user_id": user_id}
    )
            
    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            
            if message_type == "offer":
                # Broadcast offer to other users in room
                await connection_manager.broadcast_to_room({
                    "type": "offer",
                    "offer": data["offer"],
                    "sender": user_id
                }, room_id, exclude_user_id=user_id)
            
            elif message_type == "answer":
                # Send answer to specific user
                target_user = data.get("target")
                if target_user:
                    await connection_manager.send_to_user(room_id, target_user, {
                        "type": "answer",
                        "answer": data["answer"],
                        "sender": user_id
                    })

            elif message_type == "call-request":
                sender_id = data.get("sender")
                sender_username = data.get("sender_username")
                target_user = data.get("target")
                
                if target_user:
                    await connection_manager.send_call_request(room_id, 
                                                               from_user_id=sender_id, 
                                                               to_user_id=target_user,
                                                               from_username=sender_username)
            
            elif message_type == "call-response":
                accepted = data.get("accepted")
                target = data.get("target")
                from_user_id = data.get("from_user_id")

                if accepted and target:
                    await connection_manager.send_call_response(room_id, from_user_id, 
                                                                to_user_id=target,
                                                                accepted=accepted)

            elif message_type == "ice-candidate":
                target_user = data.get("target")
                candidate = data.get("candidate")
                if target_user and candidate:
                    await connection_manager.send_to_user(
                        room_id,
                        target_user,
                        {
                            "type": "ice-candidate",
                            "candidate": candidate,
                            "sender": user_id
                        }
                    )
            
            elif message_type == "user-joined":
                # Notify others about new user
                await connection_manager.broadcast_to_room({
                    "type": "user-joined",
                    "user": user_id
                }, room_id, exclude_user_id=user_id)
            
            elif message_type == "user-left":
                # Notify others about user leaving
                await connection_manager.broadcast_to_room({
                    "type": "user-left",
                    "user": user_id
                }, room_id, exclude_user_id=user_id)
            
            elif message_type == "screen-sharing":
                # Notify about screen sharing
                await connection_manager.broadcast_to_room({
                    "type": "screen-sharing",
                    "isSharing": data["isSharing"],
                    "sender": user_id
                }, room_id, exclude_user_id=user_id)
    
    except WebSocketDisconnect:
        connection_manager.disconnect(room_id, user_id)
        await connection_manager.broadcast_to_room({
            "type": "user-left",
            "user": user_id
        }, room_id)