from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status, Cookie
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth, convert_objectid

router = APIRouter(prefix="/progress", tags=["progress"])



# 카테고리 프로그레스
@router.post("/categories/{category_id}")
async def initialize_category_progress(
    category_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """카테고리 프로그레스 초기화"""
    user_id = require_auth(request)
    
    try:
        category_obj_id = ObjectId(category_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid category ID"
        )
    
    existing_progress = await db.User_Category_Progress.find_one({
        "user_id": ObjectId(user_id),
        "category_id": category_obj_id
    })
    
    if existing_progress:
        return JSONResponse(
            status_code=status.HTTP_200_OK, 
            content={"success": True, "message": "이미 초기화됨"}
        )
    
    await db.User_Category_Progress.insert_one({
        "user_id": ObjectId(user_id),
        "category_id": category_obj_id,
        "complete": False,
        "complete_at": None
    })
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, 
        content={"success": True, "message": "카테고리 진도 초기화 완료"}
    )

# 챕터 프로그레스
@router.post("/chapters/{chapter_id}")
async def initialize_chapter_progress(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 프로그레스 초기화"""
    user_id = require_auth(request)
    
    try:
        chapter_obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    existing_progress = await db.User_Chapter_Progress.find_one({
        "user_id": ObjectId(user_id),
        "chapter_id": chapter_obj_id
    })
    
    if existing_progress:
        return JSONResponse(
            status_code=status.HTTP_200_OK, 
            content={"success": True, "message": "이미 초기화됨"}
        )
    
    await db.User_Chapter_Progress.insert_one({
        "user_id": ObjectId(user_id),
        "chapter_id": chapter_obj_id,
        "complete": False,
        "complete_at": None
    })
    
    # 하위 레슨 진도도 초기화
    lessons = await db.Lessons.find({"chapter_id": chapter_obj_id}).to_list(length=None)
    progress_bulk = [{
        "user_id": ObjectId(user_id),
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

# 레슨 이벤트 업데이트
@router.post("/lessons/events")
async def update_lesson_events(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 이벤트 업데이트"""
    user_id = require_auth(request)
    data = await request.json()
    lesson_ids = [ObjectId(lid) for lid in data.get("lesson_ids", [])]
    
    await db.User_Lesson_Progress.update_many(
        {"user_id": ObjectId(user_id), "lesson_id": {"$in": lesson_ids}},
        {"$set": {"last_event_at": datetime.utcnow()}}
    )
    
    return {
        "success": True,
        "message": "last_event_at 업데이트 완료"
    }

# 전체 진도 개요
@router.get("/overview")
async def get_progress_overview(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """전체 진도 개요 조회"""
    user_id = require_auth(request)
    
    # 전체 레슨 수
    total_lessons = await db.Lessons.count_documents({})
    # reviewed 상태인 레슨 수
    reviewed_count = await db.User_Lesson_Progress.count_documents({
        "user_id": ObjectId(user_id),
        "status": "reviewed"
    })
    
    # 전체 진도율
    overall_progress = int((reviewed_count / total_lessons) * 100) if total_lessons > 0 else 0
    
    # 카테고리별 진도율 (챕터 단위)
    categories = await db.Category.find().to_list(length=None)
    category_progress = []
    
    for category in categories:
        # 카테고리 내 챕터 목록
        chapters = await db.Chapters.find({"category_id": category["_id"]}).to_list(length=None)
        total_chapters = len(chapters)
        completed_chapters = 0
        
        for chapter in chapters:
            lesson_ids = [l["_id"] for l in await db.Lessons.find({"chapter_id": chapter["_id"]}).to_list(length=None)]
            total = len(lesson_ids)
            if total == 0:
                continue
            reviewed = await db.User_Lesson_Progress.count_documents({
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": lesson_ids},
                "status": "reviewed"
            })
            if reviewed == total:
                completed_chapters += 1
        
        # 카테고리별 전체 레슨/완료 레슨도 기존대로 포함
        lesson_ids = [l["_id"] for l in await db.Lessons.find({"chapter_id": {"$in": [c["_id"] for c in chapters]}}).to_list(length=None)]
        total_lessons_in_cat = len(lesson_ids)
        reviewed_lessons_in_cat = await db.User_Lesson_Progress.count_documents({
            "user_id": ObjectId(user_id),
            "lesson_id": {"$in": lesson_ids},
            "status": "reviewed"
        })
        progress = int((reviewed_lessons_in_cat / total_lessons_in_cat) * 100) if total_lessons_in_cat > 0 else 0
        
        category_progress.append({
            "id": str(category["_id"]),
            "name": category["name"],
            "description": category.get("description", ""),
            "progress": progress,
            "completed_chapters": completed_chapters,
            "total_chapters": total_chapters,
            "completed_lessons": reviewed_lessons_in_cat,
            "total_lessons": total_lessons_in_cat,
            "status": "completed" if completed_chapters == total_chapters and total_chapters > 0 else "in_progress"
        })
    
    # 챕터별 완료 여부 계산 (전체)
    chapters = await db.Chapters.find().to_list(length=None)
    completed_chapter_count = 0
    
    for chapter in chapters:
        lesson_ids = [l["_id"] for l in await db.Lessons.find({"chapter_id": chapter["_id"]}).to_list(length=None)]
        total = len(lesson_ids)
        if total == 0:
            continue
        reviewed = await db.User_Lesson_Progress.count_documents({
            "user_id": ObjectId(user_id),
            "lesson_id": {"$in": lesson_ids},
            "status": "reviewed"
        })
        if reviewed == total:
            completed_chapter_count += 1
    
    return {
        "success": True,
        "data": {
            "overall_progress": overall_progress,
            "completed_chapters": completed_chapter_count,
            "total_chapters": len(chapters),
            "total_lessons": total_lessons,
            "categories": category_progress or []
        },
        "message": "진도 개요 조회 성공"
    }

# 최근 학습 조회
@router.get("/recent-learning")
async def get_recent_learning(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """최근 학습 조회"""
    user_id = require_auth(request)
    
    progress = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id)
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

# 실패한 레슨 조회
@router.get("/failures/{username}")
async def get_failed_lessons_by_username(
    username: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자별 실패한 레슨 조회"""
    # username으로 user 찾기
    user = await db.users.find_one({"nickname": username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="User not found"
        )
    
    user_id = user["_id"]
    
    # 해당 user_id로 실패한 progress 조회
    failed_progresses = await db.Progress.find({
        "user_id": user_id,
        "status": "fail"
    }).to_list(length=None)
    
    # lesson_id 목록 추출
    lesson_ids = [p["lesson_id"] for p in failed_progresses]
    if not lesson_ids:
        return {
            "success": True,
            "data": [],
            "message": "실패한 레슨 없음"
        }
    
    # lesson_id로 Lessons 조회
    lessons = await db.Lessons.find({
        "_id": {"$in": lesson_ids}
    }).to_list(length=None)
    
    # 각 레슨에 category 이름과 word 필드 추가
    for lesson in lessons:
        # chapter 정보 가져오기
        chapter = await db.Chapters.find_one({"_id": lesson["chapter_id"]})
        category = await db.Category.find_one({"_id": chapter["category_id"]}) if chapter else None
        
        # category 이름 추가
        lesson["category"] = category["name"] if category else "Unknown"
        
        # word 필드에 sign을 복사
        lesson["word"] = lesson.get("sign_text", "")
    
    return {
        "success": True,
        "data": convert_objectid(lessons),
        "message": "실패한 레슨 조회 성공"
    } 