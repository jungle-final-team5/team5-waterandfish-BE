from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth, convert_objectid

router = APIRouter(prefix="/quiz", tags=["quiz"])





# /quiz/chapter/:chapterId 라우트용
@router.get("/chapter/{chapter_id}")
async def get_chapter_quiz(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 퀴즈 조회 - /quiz/chapter/:chapterId 라우트용"""
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
    
    # 챕터의 모든 레슨 가져오기 (퀴즈용)
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
        "message": "챕터 퀴즈 조회 성공"
    }

# /quiz/chapter/:chapterId/review 라우트용
@router.get("/chapter/{chapter_id}/review")
async def get_chapter_quiz_review(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 퀴즈 리뷰 조회 - /quiz/chapter/:chapterId/review 라우트용"""
    user_id = require_auth(request)
    
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
    
    # 챕터의 모든 레슨과 진행 상태 가져오기
    lessons = await db.Lessons.find({"chapter_id": obj_id}).to_list(length=None)
    lesson_ids = [lesson["_id"] for lesson in lessons]
    
    progresses = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id),
        "lesson_id": {"$in": lesson_ids}
    }).to_list(length=None)
    
    progress_map = {str(p["lesson_id"]): p for p in progresses}
    
    lesson_list = []
    for lesson in lessons:
        progress = progress_map.get(str(lesson["_id"]), {})
        lesson_list.append({
            "id": str(lesson["_id"]),
            "word": lesson.get("sign_text", ""),
            "videoUrl": str(lesson.get("media_url", "")),
            "description": lesson.get("description", ""),
            "status": progress.get("status", "not_started"),
            "last_event_at": progress.get("last_event_at"),
            "updated_at": progress.get("updated_at")
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
        "message": "챕터 퀴즈 리뷰 조회 성공"
    }

# 퀴즈 결과 제출
@router.post("/chapter/{chapter_id}/submit")
async def submit_chapter_quiz(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 퀴즈 결과 제출"""
    user_id = require_auth(request)
    data = await request.json()
    
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    correct_ids = []
    wrong_ids = []
    
    for result in data.get("results", []):
        lesson_id = ObjectId(result.get("lessonId"))
        correct = result.get("correct")
        if correct:
            correct_ids.append(lesson_id)
        else:
            wrong_ids.append(lesson_id)
    
    # 퀴즈 결과에 따른 상태 업데이트
    if correct_ids and not wrong_ids:
        # 모두 정답인 경우
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": correct_ids}
            },
            {
                "$set": {
                    "status": "quiz_correct",
                    "updated_at": datetime.utcnow(),
                    "last_event_at": datetime.utcnow()
                }
            }
        )
    elif wrong_ids:
        # 오답이 있는 경우
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": correct_ids + wrong_ids}
            },
            {
                "$set": {
                    "status": "quiz_wrong",
                    "updated_at": datetime.utcnow(),
                    "last_event_at": datetime.utcnow()
                }
            }
        )
    
    return {
        "success": True,
        "data": {
            "correct_count": len(correct_ids),
            "wrong_count": len(wrong_ids),
            "total_count": len(correct_ids) + len(wrong_ids)
        },
        "message": "퀴즈 결과 제출 완료"
    } 