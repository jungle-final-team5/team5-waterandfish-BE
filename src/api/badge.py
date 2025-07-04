from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from ..models.badge import Badge, UserBadge, BadgeWithStatus
from ..core.auth import get_current_user_id, get_current_user_id_optional, decode_token, APIResponse
from bson import ObjectId
from bson.timestamp import Timestamp
from typing import List, Optional
import datetime

router = APIRouter(prefix="/badges", tags=["badges"])

def convert_timestamp(obj):
    """MongoDB Timestamp를 datetime으로 변환"""
    if isinstance(obj, Timestamp):
        return datetime.datetime.fromtimestamp(obj.time)
    return obj

@router.get("/health")
async def badge_health():
    """배지 서비스 상태 확인"""
    return APIResponse.success(message="Badge service is healthy")

@router.get("/", response_model=List[BadgeWithStatus])
async def get_all_badges(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """전체 배지 목록 조회 (사용자 인증 시 획득 상태 포함)"""
    # 옵셔널 인증 (비로그인 사용자도 배지 목록 조회 가능)
    user_id = get_current_user_id_optional(request)
    
    # 모든 배지 조회
    all_badges = await db.Badge.find().to_list(length=None)
    
    # 사용자가 획득한 배지 조회 (인증된 경우만)
    user_badges = set()
    if user_id:
        user_badge_docs = await db.users_badge.find({"userid": user_id}).to_list(length=None)
        user_badges = {badge["badge_id"] for badge in user_badge_docs}
    
    # 결과 생성
    result = []
    for badge in all_badges:
        badge_data = BadgeWithStatus(
            id=badge["id"],
            code=badge["code"],
            name=badge["name"],
            description=badge["description"],
            icon_url=badge["icon_url"],
            is_earned=badge["id"] in user_badges if user_id else False
        )
        result.append(badge_data)
    
    return result

@router.get("/earned")
async def get_earned_badges(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """현재 사용자가 획득한 배지 목록 조회"""
    user_id = get_current_user_id(request)
    
    # 사용자가 획득한 배지 조회
    user_badges = await db.users_badge.find({"userid": user_id}).to_list(length=None)
    
    # 배지 상세 정보와 함께 반환
    result = []
    for user_badge in user_badges:
        badge_detail = await db.Badge.find_one({"id": user_badge["badge_id"]})
        if badge_detail:
            badge_info = {
                "id": badge_detail["id"],
                "code": badge_detail["code"],
                "name": badge_detail["name"],
                "description": badge_detail["description"],
                "icon_url": badge_detail["icon_url"],
                "earned_at": convert_timestamp(user_badge["acquire"]),
                "link": user_badge.get("link", "")
            }
            result.append(badge_info)
    
    return APIResponse.success(data={
        "badges": result,
        "total": len(result)
    })

@router.get("/{badge_id}")
async def get_badge_detail(
    badge_id: int,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """배지 상세 정보 조회"""
    # 배지 존재 확인
    badge = await db.Badge.find_one({"id": badge_id})
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    
    # 사용자 획득 여부 확인 (옵셔널)
    user_id = get_current_user_id_optional(request)
    is_earned = False
    earned_at = None
    
    if user_id:
        user_badge = await db.users_badge.find_one({
            "userid": user_id,
            "badge_id": badge_id
        })
        if user_badge:
            is_earned = True
            earned_at = convert_timestamp(user_badge["acquire"])
    
    badge_detail = {
        "id": badge["id"],
        "code": badge["code"],
        "name": badge["name"],
        "description": badge["description"],
        "icon_url": badge["icon_url"],
        "is_earned": is_earned,
        "earned_at": earned_at
    }
    
    return APIResponse.success(data=badge_detail)

@router.post("/{badge_id}/earn")
async def earn_badge(
    badge_id: int,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """배지 획득"""
    user_id = get_current_user_id(request)
    
    # 배지 존재 확인
    badge = await db.Badge.find_one({"id": badge_id})
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    
    # 이미 획득했는지 확인
    existing_badge = await db.users_badge.find_one({
        "userid": user_id,
        "badge_id": badge_id
    })
    if existing_badge:
        raise HTTPException(status_code=409, detail="Badge already earned")
    
    # 배지 획득 기록
    user_badge = {
        "badge_id": badge_id,
        "userid": user_id,
        "link": "earned",
        "acquire": datetime.datetime.utcnow()
    }
    
    await db.users_badge.insert_one(user_badge)
    
    return APIResponse.success(
        data={
            "badge_id": badge_id,
            "badge_name": badge["name"],
            "earned_at": user_badge["acquire"]
        },
        message=f"Badge '{badge['name']}' earned successfully!"
    )

@router.delete("/{badge_id}")
async def remove_badge(
    badge_id: int,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """배지 제거 (관리자 또는 테스트용)"""
    user_id = get_current_user_id(request)
    
    # 배지 존재 확인
    badge = await db.Badge.find_one({"id": badge_id})
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    
    # 사용자가 획득한 배지인지 확인
    user_badge = await db.users_badge.find_one({
        "userid": user_id,
        "badge_id": badge_id
    })
    if not user_badge:
        raise HTTPException(status_code=404, detail="Badge not earned by user")
    
    # 배지 제거
    result = await db.users_badge.delete_one({
        "userid": user_id,
        "badge_id": badge_id
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=500, detail="Failed to remove badge")
    
    return APIResponse.success(
        message=f"Badge '{badge['name']}' removed successfully"
    )

@router.get("/stats/leaderboard")
async def get_badge_leaderboard(
    limit: int = 10,
    offset: int = 0,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """배지 리더보드 조회"""
    # 사용자별 배지 수 집계
    pipeline = [
        {
            "$group": {
                "_id": "$userid",
                "badge_count": {"$sum": 1}
            }
        },
        {
            "$sort": {"badge_count": -1}
        },
        {
            "$skip": offset
        },
        {
            "$limit": limit
        }
    ]
    
    leaderboard = await db.users_badge.aggregate(pipeline).to_list(length=limit)
    
    # 사용자 정보 추가
    result = []
    for entry in leaderboard:
        user = await db.users.find_one({"_id": ObjectId(entry["_id"])}) if ObjectId.is_valid(entry["_id"]) else None
        if user:
            result.append({
                "user_id": str(user["_id"]),
                "nickname": user["nickname"],
                "badge_count": entry["badge_count"]
            })
    
    return APIResponse.success(data={
        "leaderboard": result,
        "offset": offset,
        "limit": limit
    })

@router.get("/stats/summary")
async def get_badge_stats(
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """배지 통계 조회"""
    total_badges = await db.Badge.count_documents({})
    total_earned = await db.users_badge.count_documents({})
    unique_users = len(await db.users_badge.distinct("userid"))
    
    # 가장 인기 있는 배지
    popular_badges = await db.users_badge.aggregate([
        {"$group": {"_id": "$badge_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]).to_list(length=5)
    
    popular_badge_list = []
    for badge_stat in popular_badges:
        badge = await db.Badge.find_one({"id": badge_stat["_id"]})
        if badge:
            popular_badge_list.append({
                "badge_id": badge["id"],
                "name": badge["name"],
                "earned_count": badge_stat["count"]
            })
    
    stats = {
        "total_badges": total_badges,
        "total_earned": total_earned,
        "unique_users_with_badges": unique_users,
        "average_badges_per_user": round(total_earned / unique_users, 2) if unique_users > 0 else 0,
        "popular_badges": popular_badge_list
    }
    
    return APIResponse.success(data=stats)

# 하위 호환성을 위한 deprecated 엔드포인트들
@router.get("/")
async def get_badges_deprecated(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """@deprecated Use /badges/ instead"""
    return await get_all_badges(request, db)

@router.post("/earn/{badge_id}")
async def earn_badge_deprecated(
    badge_id: int,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """@deprecated Use /badges/{badge_id}/earn instead"""
    return await earn_badge(badge_id, request, db)

@router.get("/all-earned")
async def get_all_earned_badges_deprecated(
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """@deprecated Use /badges/earned instead"""
    # 모든 users_badge 데이터 조회 (관리자용)
    all_user_badges = await db.users_badge.find().to_list(length=None)
    
    result = []
    for badge in all_user_badges:
        result.append({
            "_id": str(badge["_id"]),
            "badge_id": badge["badge_id"],
            "userid": str(badge["userid"]),
            "link": badge["link"],
            "acquire": convert_timestamp(badge["acquire"])
        })
    
    return result