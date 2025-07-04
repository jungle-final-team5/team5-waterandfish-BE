from jose import jwt, JWTError
from datetime import datetime, timedelta
from passlib.context import CryptContext
from fastapi import HTTPException, Request, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from .config import settings
from typing import Optional
from bson import ObjectId

# JWT 설정
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 검증"""
    return pwd_context.verify(plain_password, hashed_password)

def hash_password(password: str) -> str:
    """비밀번호 해싱"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """액세스 토큰 생성"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """리프레시 토큰 생성"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def extract_token_from_request(request: Request) -> Optional[str]:
    """요청에서 토큰 추출 (Authorization 헤더 또는 쿠키)"""
    # Authorization 헤더에서 토큰 추출
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    
    # 쿠키에서 토큰 추출
    return request.cookies.get("access_token")

def decode_token(token: str) -> dict:
    """토큰 디코딩"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user_id(request: Request) -> str:
    """현재 사용자 ID 추출"""
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="No token found")
    
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="No user id in token")
    
    return user_id

def get_current_user_id_optional(request: Request) -> Optional[str]:
    """현재 사용자 ID 추출 (옵셔널)"""
    try:
        return get_current_user_id(request)
    except HTTPException:
        return None

async def get_current_user(request: Request, db: AsyncIOMotorDatabase) -> dict:
    """현재 사용자 정보 반환"""
    user_id = get_current_user_id(request)
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# 표준화된 응답 형식
class APIResponse:
    @staticmethod
    def success(data=None, message="Success"):
        return {"success": True, "message": message, "data": data}
    
    @staticmethod
    def error(message="Error", code=400):
        return {"success": False, "message": message, "error_code": code}