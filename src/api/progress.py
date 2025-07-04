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
    """레슨 이벤트 업데이트 (user_id를 body에서 받음)"""
    data = await request.json()
    user_id = data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
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
    """전체 진도 개요 조회 (최적화 버전)"""
    user_id = require_auth(request)

    # 모든 데이터 한 번에 불러오기
    all_lessons = await db.Lessons.find().to_list(length=None)
    all_chapters = await db.Chapters.find().to_list(length=None)
    all_categories = await db.Category.find().to_list(length=None)
    all_progress = await db.User_Lesson_Progress.find({"user_id": ObjectId(user_id)}).to_list(length=None)

    # 인덱싱
    lesson_id_to_progress = {p["lesson_id"]: p for p in all_progress}
    chapter_id_to_lessons = {}
    for lesson in all_lessons:
        chapter_id_to_lessons.setdefault(lesson["chapter_id"], []).append(lesson["_id"])
    category_id_to_chapters = {}
    for chapter in all_chapters:
        category_id_to_chapters.setdefault(chapter["category_id"], []).append(chapter["_id"])

    # 전체 진도율
    total_lessons = len(all_lessons)
    reviewed_count = sum(1 for p in all_progress if p["status"] == "reviewed")
    overall_progress = int((reviewed_count / total_lessons) * 100) if total_lessons > 0 else 0

    # 카테고리별 진도율
    category_progress = []
    for category in all_categories:
        chapter_ids = category_id_to_chapters.get(category["_id"], [])
        lesson_ids = [lid for cid in chapter_ids for lid in chapter_id_to_lessons.get(cid, [])]
        total_lessons_in_cat = len(lesson_ids)
        reviewed_lessons_in_cat = sum(1 for lid in lesson_ids if lesson_id_to_progress.get(lid, {}).get("status") == "reviewed")
        # 챕터별 완료 여부
        completed_chapters = 0
        for cid in chapter_ids:
            lids = chapter_id_to_lessons.get(cid, [])
            if lids:
                if all(lesson_id_to_progress.get(lid, {}).get("status") == "reviewed" for lid in lids):
                    completed_chapters += 1
        total_chapters = len(chapter_ids)
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

    # 전체 챕터별 완료 여부
    completed_chapter_count = 0
    for chapter in all_chapters:
        lids = chapter_id_to_lessons.get(chapter["_id"], [])
        if lids and all(lesson_id_to_progress.get(lid, {}).get("status") == "reviewed" for lid in lids):
            completed_chapter_count += 1

    return {
        "success": True,
        "data": {
            "overall_progress": overall_progress,
            "completed_chapters": completed_chapter_count,
            "total_chapters": len(all_chapters),
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

@router.post("/chapters/{chapter_id}/lessons")
async def update_chapter_lessons_progress(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """특정 챕터 내 여러 레슨의 학습 진행 상태 일괄 업데이트"""
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