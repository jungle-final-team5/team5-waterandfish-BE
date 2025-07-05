from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth, convert_objectid

router = APIRouter(prefix="/learn", tags=["learn"])





# /learn/word/:wordId 라우트용
@router.get("/word/{word_id}")
async def get_word_lesson(
    word_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """특정 단어 레슨 조회 - /learn/word/:wordId 라우트용"""
    try:
        obj_id = ObjectId(word_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid word ID"
        )
    
    lesson = await db.Lessons.find_one({"_id": obj_id})
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Word lesson not found"
        )
    
    # 챕터 정보 가져오기
    chapter = await db.Chapters.find_one({"_id": lesson["chapter_id"]})
    if chapter:
        # 카테고리 정보 가져오기
        category = await db.Category.find_one({"_id": chapter["category_id"]})
        lesson["category_name"] = category["name"] if category else "Unknown"
        lesson["chapter_title"] = chapter["title"]
    
    return {
        "success": True,
        "data": convert_objectid(lesson),
        "message": "단어 레슨 조회 성공"
    }

# /learn/chapter/:chapterId 라우트용
@router.get("/chapter/{chapter_id}")
async def get_chapter_session(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 학습 세션 조회 - /learn/chapter/:chapterId 라우트용"""
    user_id = get_user_id_from_token(request)
    
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    chapter = await db.Chapters.find_one({"_id": obj_id})
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Chapter not found"
        )
    
    # 챕터의 모든 레슨 가져오기
    lessons = await db.Lessons.find({"chapter_id": obj_id}).to_list(length=None)
    lesson_ids = [lesson["_id"] for lesson in lessons]
    lesson_status_map = {}
    
    if user_id and lesson_ids:
        progresses = await db.User_Lesson_Progress.find({
            "user_id": ObjectId(user_id),
            "lesson_id": {"$in": lesson_ids}
        }).to_list(length=None)
        
        for progress in progresses:
            lesson_status_map[str(progress["lesson_id"])] = progress.get("status", "not_started")
    
    lesson_list = []
    for lesson in lessons:
        lesson_list.append({
            "id": str(lesson["_id"]),
            "word": lesson.get("sign_text", ""),
            "videoUrl": str(lesson.get("media_url", "")),
            "description": lesson.get("description", ""),
            "status": lesson_status_map.get(str(lesson["_id"]), "not_started")
        })
    
    # 카테고리 정보 가져오기
    category = await db.Category.find_one({"_id": chapter["category_id"]})
    
    result = {
        "id": str(chapter["_id"]),
        "title": chapter["title"],
        "type": chapter.get("lesson_type", None),
        "category_name": category["name"] if category else "Unknown",
        "lessons": lesson_list,
        "order_index": chapter.get("order_index", 0)
    }
    
    return {
        "success": True,
        "data": result,
        "message": "챕터 학습 세션 조회 성공"
    }

# /learn/chapter/:chapterId/guide 라우트용
@router.get("/chapter/{chapter_id}/guide")
async def get_chapter_guide(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 학습 가이드 조회 - /learn/chapter/:chapterId/guide 라우트용"""
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    chapter = await db.Chapters.find_one({"_id": obj_id})
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Chapter not found"
        )
    
    # 카테고리 정보 가져오기
    category = await db.Category.find_one({"_id": chapter["category_id"]})
    
    # 챕터의 모든 레슨 가져오기 (가이드용)
    lessons = await db.Lessons.find({"chapter_id": obj_id}).to_list(length=None)
    lesson_list = []
    
    for lesson in lessons:
        lesson_list.append({
            "id": str(lesson["_id"]),
            "word": lesson.get("sign_text", ""),
            "videoUrl": str(lesson.get("media_url", "")),
            "description": lesson.get("description", ""),
            "order_index": lesson.get("order_index", 0)
        })
    
    result = {
        "id": str(chapter["_id"]),
        "title": chapter["title"],
        "type": chapter.get("lesson_type", None),
        "category_name": category["name"] if category else "Unknown",
        "description": chapter.get("description", ""),
        "lessons": lesson_list,
        "order_index": chapter.get("order_index", 0)
    }
    
    return {
        "success": True,
        "data": result,
        "message": "챕터 학습 가이드 조회 성공"
    }

# 학습 진행 상태 업데이트
@router.post("/chapter/{chapter_id}/progress")
async def update_chapter_progress(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 학습 진행 상태 업데이트"""
    user_id = require_auth(request)
    data = await request.json()
    
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    lesson_ids = data.get("lesson_ids", [])
    status = data.get("status", "study")
    
    if lesson_ids:
        lesson_obj_ids = [ObjectId(lid) for lid in lesson_ids]
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": lesson_obj_ids}
            },
            {
                "$set": {
                    "status": status,
                    "updated_at": datetime.utcnow(),
                    "last_event_at": datetime.utcnow()
                }
            }
        )
    
    return {
        "success": True,
        "message": "학습 진행 상태 업데이트 완료"
    } 