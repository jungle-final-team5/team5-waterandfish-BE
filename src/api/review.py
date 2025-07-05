from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth, convert_objectid

router = APIRouter(prefix="/review", tags=["review"])





# /review 라우트용
@router.get("")
async def get_review_page(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """리뷰 페이지 조회 - /review 라우트용"""
    user_id = require_auth(request)
    
    # 사용자의 모든 진행 상태 가져오기
    progresses = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id)
    }).to_list(length=None)
    
    # 레슨 ID 목록 추출
    lesson_ids = [p["lesson_id"] for p in progresses]
    
    if not lesson_ids:
        return {
            "success": True,
            "data": {
                "review_items": [],
                "total_count": 0,
                "reviewed_count": 0
            },
            "message": "리뷰할 항목이 없습니다"
        }
    
    # 레슨 정보 가져오기
    lessons = await db.Lessons.find({
        "_id": {"$in": lesson_ids}
    }).to_list(length=None)
    
    # 챕터 정보 가져오기
    chapter_ids = list(set([lesson["chapter_id"] for lesson in lessons]))
    chapters = await db.Chapters.find({
        "_id": {"$in": chapter_ids}
    }).to_list(length=None)
    
    # 카테고리 정보 가져오기
    category_ids = list(set([chapter["category_id"] for chapter in chapters]))
    categories = await db.Category.find({
        "_id": {"$in": category_ids}
    }).to_list(length=None)
    
    # 매핑 생성
    chapter_map = {str(c["_id"]): c for c in chapters}
    category_map = {str(c["_id"]): c for c in categories}
    progress_map = {str(p["lesson_id"]): p for p in progresses}
    
    review_items = []
    reviewed_count = 0
    
    for lesson in lessons:
        progress = progress_map.get(str(lesson["_id"]), {})
        chapter = chapter_map.get(str(lesson["chapter_id"]), {})
        category = category_map.get(str(chapter.get("category_id", "")), {})
        
        status = progress.get("status", "not_started")
        if status == "reviewed":
            reviewed_count += 1
        
        review_items.append({
            "id": str(lesson["_id"]),
            "word": lesson.get("sign_text", ""),
            "videoUrl": str(lesson.get("media_url", "")),
            "description": lesson.get("description", ""),
            "status": status,
            "chapter_title": chapter.get("title", ""),
            "category_name": category.get("name", ""),
            "last_event_at": progress.get("last_event_at"),
            "updated_at": progress.get("updated_at")
        })
    
    # 최근 학습 순으로 정렬
    review_items.sort(
        key=lambda x: x["last_event_at"] if x["last_event_at"] else datetime.min,
        reverse=True
    )
    
    return {
        "success": True,
        "data": {
            "review_items": review_items or [],
            "total_count": len(review_items),
            "reviewed_count": reviewed_count
        },
        "message": "리뷰 페이지 조회 성공"
    }

# 리뷰 상태 업데이트
@router.post("/mark-reviewed")
async def mark_as_reviewed(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨을 리뷰 완료로 표시"""
    user_id = require_auth(request)
    data = await request.json()
    
    lesson_ids = [ObjectId(lid) for lid in data.get("lesson_ids", [])]
    
    if lesson_ids:
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": lesson_ids}
            },
            {
                "$set": {
                    "status": "reviewed",
                    "updated_at": datetime.utcnow(),
                    "last_event_at": datetime.utcnow()
                }
            }
        )
    
    return {
        "success": True,
        "message": "리뷰 완료로 표시되었습니다"
    }

# 리뷰 통계
@router.get("/stats")
async def get_review_stats(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """리뷰 통계 조회"""
    user_id = require_auth(request)
    
    # 전체 레슨 수
    total_lessons = await db.Lessons.count_documents({})
    
    # 사용자의 진행 상태 통계
    stats = await db.User_Lesson_Progress.aggregate([
        {"$match": {"user_id": ObjectId(user_id)}},
        {
            "$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }
        }
    ]).to_list(length=None)
    
    # 통계 맵 생성
    stats_map = {item["_id"]: item["count"] for item in stats}
    
    result = {
        "total_lessons": total_lessons,
        "not_started": stats_map.get("not_started", 0),
        "study": stats_map.get("study", 0),
        "quiz_wrong": stats_map.get("quiz_wrong", 0),
        "quiz_correct": stats_map.get("quiz_correct", 0),
        "reviewed": stats_map.get("reviewed", 0)
    }
    
    # 진행률 계산
    if total_lessons > 0:
        result["progress_percentage"] = int((result["reviewed"] / total_lessons) * 100)
    else:
        result["progress_percentage"] = 0
    
    return {
        "success": True,
        "data": result,
        "message": "리뷰 통계 조회 성공"
    } 