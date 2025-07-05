from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import convert_objectid

router = APIRouter(prefix="/users", tags=["users"])



# 사용자 진도 조회
@router.get("/{user_id}/progress")
async def get_user_progress(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자의 전체 진도 조회"""
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID"
        )
    
    lesson_progress = await db.User_Lesson_Progress.find({"user_id": user_obj_id}).to_list(length=None)
    chapter_progress = await db.User_Chapter_Progress.find({"user_id": user_obj_id}).to_list(length=None)
    category_progress = await db.User_Category_Progress.find({"user_id": user_obj_id}).to_list(length=None)
    
    return {
        "success": True,
        "data": {
            "lesson_progress": convert_objectid(lesson_progress),
            "chapter_progress": convert_objectid(chapter_progress),
            "category_progress": convert_objectid(category_progress)
        },
        "message": "유저 진도 조회 성공"
    }

# 사용자 카테고리 진도 초기화
@router.post("/{user_id}/progress/categories/{category_id}")
async def set_user_category_progress(
    user_id: str,
    category_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 카테고리 진도 초기화"""
    try:
        user_obj_id = ObjectId(user_id)
        category_obj_id = ObjectId(category_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID or category ID"
        )
    
    existing_progress = await db.User_Category_Progress.find_one({
        "user_id": user_obj_id,
        "category_id": category_obj_id
    })
    
    if existing_progress:
        return JSONResponse(
            status_code=status.HTTP_200_OK, 
            content={"success": True, "message": "이미 초기화됨"}
        )
    
    await db.User_Category_Progress.insert_one({
        "user_id": user_obj_id,
        "category_id": category_obj_id,
        "complete": False,
        "complete_at": None
    })
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, 
        content={"success": True, "message": "카테고리 진도 초기화 완료"}
    )

# 사용자 챕터 진도 초기화
@router.post("/{user_id}/progress/chapters/{chapter_id}")
async def set_user_chapter_progress(
    user_id: str,
    chapter_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 챕터 진도 초기화"""
    try:
        user_obj_id = ObjectId(user_id)
        chapter_obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID or chapter ID"
        )
    
    existing_progress = await db.User_Chapter_Progress.find_one({
        "user_id": user_obj_id,
        "chapter_id": chapter_obj_id
    })
    
    if existing_progress:
        return JSONResponse(
            status_code=status.HTTP_200_OK, 
            content={"success": True, "message": "이미 초기화됨"}
        )
    
    await db.User_Chapter_Progress.insert_one({
        "user_id": user_obj_id,
        "chapter_id": chapter_obj_id,
        "complete": False,
        "complete_at": None
    })
    
    # 하위 레슨 진도도 초기화
    lessons = await db.Lessons.find({"chapter_id": chapter_obj_id}).to_list(length=None)
    progress_bulk = [{
        "user_id": user_obj_id,
        "lesson_id": lesson["_id"],
        "status": "not_started",
        "updated_at": datetime.utcnow()
    } for lesson in lessons]
    
    if progress_bulk:
        await db.User_Lesson_Progress.insert_many(progress_bulk)
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, 
        content={"success": True, "message": "챕터 및 레슨 진도 초기화 완료"}
    )

# 사용자 레슨 이벤트 업데이트
@router.post("/{user_id}/progress/lessons/events")
async def update_user_lesson_events(
    user_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 레슨 이벤트 업데이트"""
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID"
        )
    
    data = await request.json()
    lesson_ids = [ObjectId(lid) for lid in data.get("lesson_ids", [])]
    
    await db.User_Lesson_Progress.update_many(
        {"user_id": user_obj_id, "lesson_id": {"$in": lesson_ids}},
        {"$set": {"last_event_at": datetime.utcnow()}}
    )
    
    return {
        "success": True,
        "message": "last_event_at 업데이트 완료"
    }

# 사용자 진도 개요 조회
@router.get("/{user_id}/progress/overview")
async def get_user_progress_overview(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 진도 개요 조회"""
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID"
        )
    
    # 전체 레슨 수
    total_lessons = await db.Lessons.count_documents({})
    reviewed_count = await db.User_Lesson_Progress.count_documents({
        "user_id": user_obj_id,
        "status": "reviewed"
    })
    
    overall_progress = int((reviewed_count / total_lessons) * 100) if total_lessons > 0 else 0
    
    return {
        "success": True,
        "data": {"overall_progress": overall_progress},
        "message": "전체 진도율 조회 성공"
    }

# 사용자 최근 학습 조회
@router.get("/{user_id}/recent-learning")
async def get_user_recent_learning(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 최근 학습 조회"""
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID"
        )
    
    progress = await db.User_Lesson_Progress.find({
        "user_id": user_obj_id
    }).sort("last_event_at", -1).limit(1).to_list(length=1)
    
    if not progress:
        return {
            "success": True,
            "data": {"category": None, "chapter": None},
            "message": "최근 학습 없음"
        }
    
    lesson_id = progress[0]["lesson_id"]
    lesson = await db.Lessons.find_one({"_id": lesson_id})
    
    if not lesson:
        return {
            "success": True,
            "data": {"category": None, "chapter": None},
            "message": "최근 학습 없음"
        }
    
    chapter = await db.Chapters.find_one({"_id": lesson["chapter_id"]})
    if not chapter:
        return {
            "success": True,
            "data": {"category": None, "chapter": None},
            "message": "최근 학습 없음"
        }
    
    category = await db.Category.find_one({"_id": chapter["category_id"]})
    if not category:
        return {
            "success": True,
            "data": {"category": None, "chapter": chapter["title"]},
            "message": "최근 학습 있음"
        }
    
    return {
        "success": True,
        "data": {"category": category["name"], "chapter": chapter["title"]},
        "message": "최근 학습 있음"
    }

# 사용자 출석 스트릭 조회
@router.get("/{user_id}/attendance/streak")
async def get_user_streak(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 출석 스트릭 조회"""
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID"
        )
    
    activities = await db.user_daily_activity.find(
        {"user_id": user_obj_id, "has_activity": True}
    ).sort("activity_date", 1).to_list(length=None)
    
    study_dates = [a["activity_date"].strftime("%Y-%m-%d") for a in activities]
    date_list = [a["activity_date"].date() for a in activities]
    
    def calculate_streaks(dates):
        if not dates:
            return 0, 0
        
        max_streak = 1
        temp_streak = 1
        prev = dates[0]
        
        for i in range(1, len(dates)):
            if (dates[i] - prev).days == 1:
                temp_streak += 1
            else:
                temp_streak = 1
            if temp_streak > max_streak:
                max_streak = temp_streak
            prev = dates[i]
        
        current_streak = 1 if dates else 0
        for i in range(len(dates)-1, 0, -1):
            if (dates[i] - dates[i-1]).days == 1:
                current_streak += 1
            else:
                break
        
        return current_streak, max_streak
    
    current_streak, longest_streak = calculate_streaks(date_list)
    
    return {
        "success": True,
        "data": {
            "studyDates": study_dates,
            "currentStreak": current_streak,
            "longestStreak": longest_streak
        },
        "message": "출석(streak) 정보 조회 성공"
    }

# 사용자 오늘 출석 완료
@router.post("/{user_id}/attendance/complete")
async def complete_user_today_activity(
    user_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 오늘 출석 완료"""
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid user ID"
        )
    
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    result = await db.user_daily_activity.update_one(
        {"user_id": user_obj_id, "activity_date": today},
        {
            "$set": {
                "has_activity": True,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    if result.matched_count == 0:
        await db.user_daily_activity.insert_one({
            "user_id": user_obj_id,
            "activity_date": today,
            "has_activity": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
    
    return {
        "success": True,
        "message": "오늘 출석이 기록되었습니다."
    } 