from fastapi import APIRouter, Depends, HTTPException, Request, Body
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from ..services.user import UserService
from ..models.user import User, UserUpdate
from ..core.auth import get_current_user_id, get_current_user, hash_password, verify_password, APIResponse
from bson import ObjectId
from typing import Optional
#김세현 바보

router = APIRouter(prefix="/users", tags=["users"])

def get_user_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> UserService:
    return UserService(db)

@router.get("/health")
async def user_health():
    """사용자 서비스 상태 확인"""
    return APIResponse.success(message="User service is healthy")

@router.get("/me", response_model=User)
async def get_current_user_info(
    request: Request,
    user_service: UserService = Depends(get_user_service)
):
    """현재 사용자 정보 조회"""
    user_id = get_current_user_id(request)
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.get("/{user_id}", response_model=User)
async def get_user_by_id(
    user_id: str,
    user_service: UserService = Depends(get_user_service)
):
    """사용자 ID로 사용자 정보 조회"""
    try:
        ObjectId(user_id)  # 유효성 검증
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/me", response_model=User)
async def update_current_user(
    request: Request,
    user_update: UserUpdate,
    user_service: UserService = Depends(get_user_service)
):
    """현재 사용자 정보 수정"""
    user_id = get_current_user_id(request)
    updated_user = await user_service.update_user(user_id, user_update)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

@router.patch("/me", response_model=User)
async def partial_update_current_user(
    request: Request,
    user_update: UserUpdate,
    user_service: UserService = Depends(get_user_service)
):
    """현재 사용자 정보 부분 수정"""
    user_id = get_current_user_id(request)
    updated_user = await user_service.update_user(user_id, user_update)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

@router.put("/me/password")
async def change_password(
    request: Request,
    password_data: dict = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """현재 사용자 비밀번호 변경"""
    user_id = get_current_user_id(request)
    
    current_password = password_data.get("current_password")
    new_password = password_data.get("new_password")
    
    if not current_password or not new_password:
        raise HTTPException(
            status_code=400, 
            detail="Both current_password and new_password are required"
        )
    
    if len(new_password) < 8:
        raise HTTPException(
            status_code=400, 
            detail="New password must be at least 8 characters long"
        )
    
    # 현재 사용자 조회
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # 현재 비밀번호 확인
    stored_password = user.get("password_hash", "")
    if not verify_password(current_password, stored_password):
        # 기존 평문 비밀번호 호환성 (레거시)
        if current_password != stored_password:
            raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    # 새 비밀번호 해시화 및 업데이트
    hashed_password = hash_password(new_password)
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": hashed_password}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to update password")
    
    return APIResponse.success(message="Password updated successfully")

@router.get("/me/profile")
async def get_user_profile(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """현재 사용자 프로필 조회 (확장 정보 포함)"""
    user_id = get_current_user_id(request)
    
    # 사용자 기본 정보
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # 사용자 통계 정보
    total_lessons = await db.Lessons.count_documents({})
    completed_lessons = await db.User_Lesson_Progress.count_documents({
        "user_id": ObjectId(user_id),
        "status": "completed"
    })
    
    # 획득한 배지 수
    earned_badges = await db.users_badge.count_documents({"userid": user_id})
    
    profile_data = {
        "id": str(user["_id"]),
        "email": user["email"],
        "nickname": user["nickname"],
        "handedness": user.get("handedness", ""),
        "description": user.get("description", ""),
        "streak_days": user.get("streak_days", 0),
        "overall_progress": user.get("overall_progress", 0),
        "created_at": user.get("created_at"),
        "statistics": {
            "total_lessons": total_lessons,
            "completed_lessons": completed_lessons,
            "completion_rate": round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0, 2),
            "earned_badges": earned_badges
        }
    }
    
    return APIResponse.success(data=profile_data)

@router.get("/search")
async def search_users(
    q: str,
    limit: int = 10,
    offset: int = 0,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 검색"""
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")
    
    # 닉네임으로 검색
    users = await db.users.find({
        "nickname": {"$regex": q.strip(), "$options": "i"}
    }).skip(offset).limit(limit).to_list(length=limit)
    
    # 개인정보 보호를 위해 최소한의 정보만 반환
    user_list = [
        {
            "id": str(user["_id"]),
            "nickname": user["nickname"],
            "streak_days": user.get("streak_days", 0)
        }
        for user in users
    ]
    
    return APIResponse.success(data={
        "users": user_list,
        "total": len(user_list),
        "offset": offset,
        "limit": limit
    })

# 하위 호환성을 위한 deprecated 엔드포인트들
@router.get("/me", response_model=User)
async def get_me_deprecated(
    request: Request,
    user_service: UserService = Depends(get_user_service)
):
    """@deprecated Use /users/me instead"""
    return await get_current_user_info(request, user_service)

@router.put("/me", response_model=User)
async def update_me_deprecated(
    request: Request,
    user_update: UserUpdate,
    user_service: UserService = Depends(get_user_service)
):
    """@deprecated Use /users/me instead"""
    return await update_current_user(request, user_update, user_service)

@router.put("/password")
async def change_password_deprecated(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """@deprecated Use /users/me/password instead"""
    data = await request.json()
    password_data = {
        "current_password": data.get("currentPassword"),
        "new_password": data.get("newPassword")
    }
    return await change_password(request, password_data, db)

