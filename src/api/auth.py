from fastapi import APIRouter, HTTPException, Depends, Request, Body
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from ..models.user import User
from ..services.social_auth import SocialAuthService
from ..core.config import settings
from ..core.auth import (
    verify_password, hash_password, create_access_token, create_refresh_token,
    get_current_user_id, decode_token, APIResponse
)
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from fastapi.responses import RedirectResponse, JSONResponse
from bson import ObjectId

router = APIRouter(prefix="/auth", tags=["authentication"])

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    nickname: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

@router.get("/health")
async def auth_health():
    """인증 서비스 상태 확인"""
    return APIResponse.success(message="Authentication service is healthy")

async def ensure_daily_activity(user_id: str, db: AsyncIOMotorDatabase):
    """일일 활동 기록 보장"""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    record = await db.user_daily_activity.find_one({
        "user_id": ObjectId(user_id),
        "activity_date": today
    })
    if not record:
        await db.user_daily_activity.insert_one({
            "user_id": ObjectId(user_id),
            "activity_date": today,
            "has_activity": False,
        })

@router.post("/login")
async def login(login_data: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """사용자 로그인"""
    user = await db.users.find_one({"email": login_data.email})
    if not user or not verify_password(login_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # 일일 활동 기록 생성
    await ensure_daily_activity(str(user["_id"]), db)
    
    # 토큰 생성
    access_token = create_access_token(
        data={"sub": str(user["_id"]), "email": user["email"]}
    )
    refresh_token = create_refresh_token(
        data={"sub": str(user["_id"]), "email": user["email"]}
    )
    
    user_data = {
        "id": str(user["_id"]),
        "email": user["email"],
        "nickname": user["nickname"],
        "handedness": user.get("handedness", ""),
        "streak_days": user.get("streak_days", 0),
        "overall_progress": user.get("overall_progress", 0),
        "description": user.get("description", "")
    }
    
    response = JSONResponse(content=APIResponse.success(
        data={"user": user_data, "access_token": access_token}
    ))
    
    # 쿠키 설정
    response.set_cookie(
        key="access_token", value=access_token, httponly=True, secure=True,
        samesite="strict", max_age=30*60  # 30분
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token, httponly=True, secure=True,
        samesite="strict", max_age=7*24*60*60  # 7일
    )
    
    return response

@router.post("/register")
async def register(register_data: RegisterRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """사용자 회원가입"""
    # 이메일 중복 확인
    existing_user = await db.users.find_one({"email": register_data.email})
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")
    
    # 닉네임 중복 확인
    existing_nickname = await db.users.find_one({"nickname": register_data.nickname})
    if existing_nickname:
        raise HTTPException(status_code=409, detail="Nickname already taken")
    
    # 사용자 생성
    user_data = {
        "email": register_data.email,
        "password_hash": hash_password(register_data.password),
        "nickname": register_data.nickname,
        "handedness": "",
        "streak_days": 0,
        "overall_progress": 0,
        "description": "",
        "created_at": datetime.utcnow()
    }
    
    result = await db.users.insert_one(user_data)
    user_id = str(result.inserted_id)
    
    # 일일 활동 기록 생성
    await ensure_daily_activity(user_id, db)
    
    return APIResponse.success(
        data={"user_id": user_id, "email": register_data.email},
        message="User registered successfully"
    )

@router.post("/refresh")
async def refresh_access_token(request: Request):
    """액세스 토큰 갱신"""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token found")
    
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        
        new_access_token = create_access_token(
            data={"sub": payload.get("sub"), "email": payload.get("email")}
        )
        
        response = JSONResponse(content=APIResponse.success(
            data={"access_token": new_access_token}
        ))
        response.set_cookie(
            key="access_token", value=new_access_token, httponly=True, secure=True,
            samesite="strict", max_age=30*60
        )
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@router.post("/logout")
async def logout():
    """사용자 로그아웃"""
    response = JSONResponse(content=APIResponse.success(message="Logged out successfully"))
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response

@router.delete("/account")
async def delete_account(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    data: dict = Body(...)
):
    """계정 삭제"""
    user_id = get_current_user_id(request)
    password = data.get("password")
    
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")
    
    # 사용자 확인
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # 비밀번호 확인
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    # 사용자 삭제
    await db.users.delete_one({"_id": ObjectId(user_id)})
    
    # 관련 데이터 삭제
    await db.user_daily_activity.delete_many({"user_id": ObjectId(user_id)})
    await db.User_Lesson_Progress.delete_many({"user_id": ObjectId(user_id)})
    await db.users_badge.delete_many({"userid": user_id})
    
    response = JSONResponse(content=APIResponse.success(message="Account deleted successfully"))
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response

# OAuth 엔드포인트들
@router.get("/oauth/google")
async def google_oauth_start():
    """Google OAuth 시작"""
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"response_type=code&"
        f"client_id={settings.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={settings.GOOGLE_REDIRECT_URI}&"
        f"scope=openid%20email%20profile"
    )
    return RedirectResponse(url=auth_url)

@router.get("/oauth/google/callback")
async def google_oauth_callback(code: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Google OAuth 콜백"""
    try:
        social_auth = SocialAuthService(db)
        result = await social_auth.google_oauth(code)
        
        # 일일 활동 기록 생성
        await ensure_daily_activity(result["user"]["_id"], db)
        
        # 리프레시 토큰 생성
        refresh_token = create_refresh_token(
            data={"sub": result["user"]["_id"], "email": result["user"]["email"]}
        )
        
        # 프론트엔드로 리다이렉트
        user = result["user"]
        redirect_url = (
            f"{settings.FRONTEND_URL}/auth/callback?"
            f"user_id={user['_id']}&"
            f"email={user['email']}&"
            f"nickname={user['nickname']}&"
            f"handedness={user.get('handedness', '')}&"
            f"streak_days={user.get('streak_days', 0)}&"
            f"overall_progress={user.get('overall_progress', 0)}&"
            f"description={user.get('description', '')}"
        )
        
        response = RedirectResponse(url=redirect_url)
        response.set_cookie(
            key="access_token", value=result["access_token"], httponly=True,
            secure=True, samesite="strict", max_age=30*60
        )
        response.set_cookie(
            key="refresh_token", value=refresh_token, httponly=True,
            secure=True, samesite="strict", max_age=7*24*60*60
        )
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Google OAuth failed: {str(e)}")

@router.get("/oauth/kakao")
async def kakao_oauth_start():
    """Kakao OAuth 시작"""
    auth_url = (
        f"https://kauth.kakao.com/oauth/authorize?"
        f"client_id={settings.KAKAO_CLIENT_ID}&"
        f"redirect_uri={settings.KAKAO_REDIRECT_URI}&"
        f"response_type=code"
    )
    return RedirectResponse(url=auth_url)

@router.get("/oauth/kakao/callback")
async def kakao_oauth_callback(code: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Kakao OAuth 콜백"""
    try:
        social_auth = SocialAuthService(db)
        result = await social_auth.kakao_oauth(code)
        
        # 일일 활동 기록 생성
        await ensure_daily_activity(result["user"]["_id"], db)
        
        # 리프레시 토큰 생성
        refresh_token = create_refresh_token(
            data={"sub": result["user"]["_id"], "email": result["user"]["email"]}
        )
        
        # 프론트엔드로 리다이렉트
        user = result["user"]
        redirect_url = (
            f"{settings.FRONTEND_URL}/auth/callback?"
            f"user_id={user['_id']}&"
            f"email={user['email']}&"
            f"nickname={user['nickname']}&"
            f"handedness={user.get('handedness', '')}&"
            f"streak_days={user.get('streak_days', 0)}&"
            f"overall_progress={user.get('overall_progress', 0)}&"
            f"description={user.get('description', '')}"
        )
        
        response = RedirectResponse(url=redirect_url)
        response.set_cookie(
            key="access_token", value=result["access_token"], httponly=True,
            secure=True, samesite="strict", max_age=30*60
        )
        response.set_cookie(
            key="refresh_token", value=refresh_token, httponly=True,
            secure=True, samesite="strict", max_age=7*24*60*60
        )
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Kakao OAuth failed: {str(e)}")

# 하위 호환성을 위한 기존 엔드포인트들 (deprecated)
@router.post("/signin")
async def signin_deprecated(login_data: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use /auth/login instead"""
    return await login(login_data, db)

@router.post("/signup")
async def signup_deprecated(register_data: RegisterRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use /auth/register instead"""
    return await register(register_data, db)

@router.get("/google")
async def google_auth_deprecated():
    """@deprecated Use /auth/oauth/google instead"""
    return await google_oauth_start()

@router.get("/google/callback")
async def google_callback_deprecated(code: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use /auth/oauth/google/callback instead"""
    return await google_oauth_callback(code, db)

@router.get("/kakao")
async def kakao_auth_deprecated():
    """@deprecated Use /auth/oauth/kakao instead"""
    return await kakao_oauth_start()

@router.get("/kakao/callback")
async def kakao_callback_deprecated(code: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use /auth/oauth/kakao/callback instead"""
    return await kakao_oauth_callback(code, db)

@router.delete("/delete-account")
async def delete_account_deprecated(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    data: dict = Body(...)
):
    """@deprecated Use /auth/account instead"""
    return await delete_account(request, db, data)