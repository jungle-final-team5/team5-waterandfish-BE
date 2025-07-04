from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException, Depends, Cookie
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from ..core.auth import get_current_user_id, get_current_user_id_optional, decode_token, APIResponse
from ..core.config import settings
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

# 메인 라우터
router = APIRouter(prefix="/learning", tags=["learning"])

# 사용자 일일 활동 라우터 (별도 관리)
user_daily_activity_router = APIRouter(prefix="/streaks", tags=["streaks"])

# 상수
CHAPTER_TYPES = ["word", "sentence"]
LESSON_TYPES = ["letter", "word", "sentence"]

# Pydantic 모델들
class CategoryCreate(BaseModel):
    name: str
    description: str
    order: int

class ChapterCreate(BaseModel):
    title: str
    description: str
    category_name: str
    order: int
    type: str

class LessonCreate(BaseModel):
    sign: str
    description: str
    type: str
    order: int
    chapter: str
    url: str

class StudySessionCreate(BaseModel):
    lesson_ids: List[str]
    session_type: str = "practice"

class StudyResult(BaseModel):
    lesson_id: str
    status: str
    score: Optional[int] = None
    time_spent: Optional[int] = None

# 유틸리티 함수
def convert_objectid(doc):
    """ObjectId를 JSON에 맞게 문자열로 변환"""
    if isinstance(doc, list):
        return [convert_objectid(item) for item in doc]
    elif isinstance(doc, dict):
        new_doc = {}
        for key, value in doc.items():
            if key == "_id":
                new_doc["id"] = str(value)
            elif isinstance(value, ObjectId):
                new_doc[key] = str(value)
            else:
                new_doc[key] = convert_objectid(value)
        return new_doc
    return doc

@router.get("/health")
async def learning_health():
    """학습 서비스 상태 확인"""
    return APIResponse.success(message="Learning service is healthy")

# =============== 카테고리 관련 엔드포인트 ===============
@router.get("/categories")
async def get_categories(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    include_progress: bool = True
):
    """카테고리 목록 조회 (진행 상태 포함)"""
    user_id = get_current_user_id_optional(request)
    
    categories = await db.Category.find().sort("order", 1).to_list(length=None)
    results = []
    
    for category in categories:
        category_id = category["_id"]
        chapters = await db.Chapters.find({"category_id": category_id}).sort("order", 1).to_list(length=None)
        
        chapter_list = []
        for chapter in chapters:
            chapter_id = chapter["_id"]
            lessons = await db.Lessons.find({"chapter_id": chapter_id}).sort("order_index", 1).to_list(length=None)
            
            # 사용자 진행 상태 계산
            lesson_status_map = {}
            if user_id and lessons:
                lesson_ids = [lesson["_id"] for lesson in lessons]
                progresses = await db.User_Lesson_Progress.find({
                    "user_id": ObjectId(user_id),
                    "lesson_id": {"$in": lesson_ids}
                }).to_list(length=None)
                
                for progress in progresses:
                    lesson_status_map[str(progress["lesson_id"])] = progress.get("status", "not_started")
            
            # 레슨 목록 생성
            lesson_list = []
            for lesson in lessons:
                lesson_data = {
                    "id": str(lesson["_id"]),
                    "sign_text": lesson.get("sign_text", ""),
                    "content_type": lesson.get("content_type", ""),
                    "description": lesson.get("description", ""),
                    "media_url": lesson.get("media_url", ""),
                    "order_index": lesson.get("order_index", 0),
                    "status": lesson_status_map.get(str(lesson["_id"]), "not_started") if user_id else "not_started"
                }
                lesson_list.append(lesson_data)
            
            chapter_data = {
                "id": str(chapter["_id"]),
                "title": chapter["title"],
                "description": chapter.get("description", ""),
                "type": chapter.get("type", ""),
                "order_index": chapter.get("order", 0),
                "lessons": lesson_list,
                "lesson_count": len(lesson_list)
            }
            chapter_list.append(chapter_data)
        
        category_data = {
            "id": str(category["_id"]),
            "name": category["name"],
            "description": category.get("description", ""),
            "order_index": category.get("order", 0),
            "chapters": chapter_list,
            "chapter_count": len(chapter_list)
        }
        results.append(category_data)
    
    return APIResponse.success(data={
        "categories": results,
        "total": len(results)
    })

@router.post("/categories")
async def create_category(
    category_data: CategoryCreate,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """카테고리 생성"""
    category = {
        "name": category_data.name,
        "description": category_data.description,
        "order": category_data.order,
        "created_at": datetime.utcnow()
    }
    
    result = await db.Category.insert_one(category)
    created_category = await db.Category.find_one({"_id": result.inserted_id})
    
    return APIResponse.success(
        data=convert_objectid(created_category),
        message="Category created successfully"
    )

@router.get("/categories/{category_id}")
async def get_category(
    category_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """카테고리 상세 조회"""
    try:
        category_object_id = ObjectId(category_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid category ID")
    
    category = await db.Category.find_one({"_id": category_object_id})
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # 카테고리의 챕터들과 레슨들 조회
    user_id = get_current_user_id_optional(request)
    chapters = await db.Chapters.find({"category_id": category_object_id}).sort("order", 1).to_list(length=None)
    
    chapter_list = []
    for chapter in chapters:
        lessons = await db.Lessons.find({"chapter_id": chapter["_id"]}).sort("order_index", 1).to_list(length=None)
        
        # 사용자 진행 상태
        lesson_status_map = {}
        if user_id and lessons:
            lesson_ids = [lesson["_id"] for lesson in lessons]
            progresses = await db.User_Lesson_Progress.find({
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": lesson_ids}
            }).to_list(length=None)
            
            for progress in progresses:
                lesson_status_map[str(progress["lesson_id"])] = progress.get("status", "not_started")
        
        lesson_list = []
        for lesson in lessons:
            lesson_data = {
                "id": str(lesson["_id"]),
                "sign_text": lesson.get("sign_text", ""),
                "content_type": lesson.get("content_type", ""),
                "description": lesson.get("description", ""),
                "media_url": lesson.get("media_url", ""),
                "order_index": lesson.get("order_index", 0),
                "status": lesson_status_map.get(str(lesson["_id"]), "not_started") if user_id else "not_started"
            }
            lesson_list.append(lesson_data)
        
        chapter_data = {
            "id": str(chapter["_id"]),
            "title": chapter["title"],
            "description": chapter.get("description", ""),
            "type": chapter.get("type", ""),
            "order_index": chapter.get("order", 0),
            "lessons": lesson_list
        }
        chapter_list.append(chapter_data)
    
    category_data = {
        "id": str(category["_id"]),
        "name": category["name"],
        "description": category.get("description", ""),
        "order_index": category.get("order", 0),
        "chapters": chapter_list
    }
    
    return APIResponse.success(data=category_data)

# =============== 챕터 관련 엔드포인트 ===============
@router.post("/chapters")
async def create_chapter(
    chapter_data: ChapterCreate,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 생성"""
    if chapter_data.type not in CHAPTER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid chapter type. Must be one of: {CHAPTER_TYPES}")
    
    # 카테고리 존재 확인
    category = await db.Category.find_one({"name": chapter_data.category_name})
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    chapter = {
        "title": chapter_data.title,
        "description": chapter_data.description,
        "type": chapter_data.type,
        "category_id": category["_id"],
        "order": chapter_data.order,
        "created_at": datetime.utcnow()
    }
    
    result = await db.Chapters.insert_one(chapter)
    created_chapter = await db.Chapters.find_one({"_id": result.inserted_id})
    
    return APIResponse.success(
        data=convert_objectid(created_chapter),
        message="Chapter created successfully"
    )

@router.get("/chapters/{chapter_id}")
async def get_chapter(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 상세 조회"""
    try:
        chapter_object_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chapter ID")
    
    chapter = await db.Chapters.find_one({"_id": chapter_object_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # 챕터의 레슨들 조회
    user_id = get_current_user_id_optional(request)
    lessons = await db.Lessons.find({"chapter_id": chapter_object_id}).sort("order_index", 1).to_list(length=None)
    
    # 사용자 진행 상태
    lesson_status_map = {}
    if user_id and lessons:
        lesson_ids = [lesson["_id"] for lesson in lessons]
        progresses = await db.User_Lesson_Progress.find({
            "user_id": ObjectId(user_id),
            "lesson_id": {"$in": lesson_ids}
        }).to_list(length=None)
        
        for progress in progresses:
            lesson_status_map[str(progress["lesson_id"])] = progress.get("status", "not_started")
    
    lesson_list = []
    for lesson in lessons:
        lesson_data = {
            "id": str(lesson["_id"]),
            "sign_text": lesson.get("sign_text", ""),
            "content_type": lesson.get("content_type", ""),
            "description": lesson.get("description", ""),
            "media_url": lesson.get("media_url", ""),
            "order_index": lesson.get("order_index", 0),
            "status": lesson_status_map.get(str(lesson["_id"]), "not_started") if user_id else "not_started"
        }
        lesson_list.append(lesson_data)
    
    chapter_data = {
        "id": str(chapter["_id"]),
        "title": chapter["title"],
        "description": chapter.get("description", ""),
        "type": chapter.get("type", ""),
        "order_index": chapter.get("order", 0),
        "lessons": lesson_list,
        "lesson_count": len(lesson_list)
    }
    
    return APIResponse.success(data=chapter_data)

# =============== 레슨 관련 엔드포인트 ===============
@router.post("/lessons")
async def create_lesson(
    lesson_data: LessonCreate,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 생성"""
    if lesson_data.type not in LESSON_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid lesson type. Must be one of: {LESSON_TYPES}")
    
    # 챕터 존재 확인
    chapter = await db.Chapters.find_one({"title": lesson_data.chapter})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    lesson = {
        "sign_text": lesson_data.sign,
        "description": lesson_data.description,
        "content_type": lesson_data.type,
        "order_index": lesson_data.order,
        "chapter_id": chapter["_id"],
        "media_url": lesson_data.url,
        "model_data_url": None,
        "created_at": datetime.utcnow()
    }
    
    result = await db.Lessons.insert_one(lesson)
    created_lesson = await db.Lessons.find_one({"_id": result.inserted_id})
    
    return APIResponse.success(
        data=convert_objectid(created_lesson),
        message="Lesson created successfully"
    )

@router.get("/lessons/{lesson_id}")
async def get_lesson(
    lesson_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 상세 조회"""
    try:
        lesson_object_id = ObjectId(lesson_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lesson ID")
    
    lesson = await db.Lessons.find_one({"_id": lesson_object_id})
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    # 사용자 진행 상태 확인
    user_id = get_current_user_id_optional(request)
    status = "not_started"
    if user_id:
        progress = await db.User_Lesson_Progress.find_one({
            "user_id": ObjectId(user_id),
            "lesson_id": lesson_object_id
        })
        if progress:
            status = progress.get("status", "not_started")
    
    lesson_data = {
        "id": str(lesson["_id"]),
        "sign_text": lesson.get("sign_text", ""),
        "content_type": lesson.get("content_type", ""),
        "description": lesson.get("description", ""),
        "media_url": lesson.get("media_url", ""),
        "order_index": lesson.get("order_index", 0),
        "chapter_id": str(lesson.get("chapter_id", "")),
        "status": status,
        "created_at": lesson.get("created_at")
    }
    
    return APIResponse.success(data=lesson_data)

# =============== 학습 진행 상황 관련 엔드포인트 ===============
@router.get("/progress")
async def get_user_progress(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 전체 학습 진행 상황 조회"""
    user_id = get_current_user_id(request)
    
    # 전체 레슨 수
    total_lessons = await db.Lessons.count_documents({})
    
    # 완료된 레슨 수
    completed_lessons = await db.User_Lesson_Progress.count_documents({
        "user_id": ObjectId(user_id),
        "status": "completed"
    })
    
    # 진행 중인 레슨 수
    in_progress_lessons = await db.User_Lesson_Progress.count_documents({
        "user_id": ObjectId(user_id),
        "status": "in_progress"
    })
    
    # 전체 진도율
    overall_progress = int((completed_lessons / total_lessons) * 100) if total_lessons > 0 else 0
    
    # 카테고리별 진행 상황
    categories = await db.Category.find().sort("order", 1).to_list(length=None)
    category_progress = []
    
    for category in categories:
        chapters = await db.Chapters.find({"category_id": category["_id"]}).to_list(length=None)
        chapter_ids = [chapter["_id"] for chapter in chapters]
        
        # 카테고리 내 전체 레슨 수
        total_lessons_in_cat = await db.Lessons.count_documents({"chapter_id": {"$in": chapter_ids}})
        
        # 카테고리 내 완료된 레슨 수
        if total_lessons_in_cat > 0:
            lesson_ids = [lesson["_id"] for lesson in await db.Lessons.find({"chapter_id": {"$in": chapter_ids}}).to_list(length=None)]
            completed_lessons_in_cat = await db.User_Lesson_Progress.count_documents({
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": lesson_ids},
                "status": "completed"
            })
            
            cat_progress = int((completed_lessons_in_cat / total_lessons_in_cat) * 100)
        else:
            completed_lessons_in_cat = 0
            cat_progress = 0
        
        category_progress.append({
            "id": str(category["_id"]),
            "name": category["name"],
            "progress": cat_progress,
            "completed_lessons": completed_lessons_in_cat,
            "total_lessons": total_lessons_in_cat,
            "status": "completed" if cat_progress == 100 else "in_progress" if cat_progress > 0 else "not_started"
        })
    
    progress_data = {
        "overall_progress": overall_progress,
        "total_lessons": total_lessons,
        "completed_lessons": completed_lessons,
        "in_progress_lessons": in_progress_lessons,
        "categories": category_progress
    }
    
    return APIResponse.success(data=progress_data)

@router.post("/progress/lessons/{lesson_id}")
async def update_lesson_progress(
    lesson_id: str,
    progress_data: dict,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 진행 상황 업데이트"""
    user_id = get_current_user_id(request)
    
    try:
        lesson_object_id = ObjectId(lesson_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lesson ID")
    
    # 레슨 존재 확인
    lesson = await db.Lessons.find_one({"_id": lesson_object_id})
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    status = progress_data.get("status", "in_progress")
    score = progress_data.get("score")
    
    # 진행 상황 업데이트
    progress_update = {
        "user_id": ObjectId(user_id),
        "lesson_id": lesson_object_id,
        "status": status,
        "updated_at": datetime.utcnow()
    }
    
    if score is not None:
        progress_update["score"] = score
    
    await db.User_Lesson_Progress.update_one(
        {"user_id": ObjectId(user_id), "lesson_id": lesson_object_id},
        {"$set": progress_update},
        upsert=True
    )
    
    # 일일 활동 기록 업데이트
    if status == "completed":
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        await db.user_daily_activity.update_one(
            {"user_id": ObjectId(user_id), "activity_date": today},
            {
                "$set": {
                    "has_activity": True,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )
    
    return APIResponse.success(message="Progress updated successfully")

# =============== 스트릭 관련 엔드포인트 ===============
@user_daily_activity_router.get("/")
async def get_user_streak(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """사용자 스트릭 조회"""
    user_id = get_current_user_id(request)
    
    # 활동 날짜 리스트 조회
    activities = await db.user_daily_activity.find({
        "user_id": ObjectId(user_id),
        "has_activity": True
    }).sort("activity_date", 1).to_list(length=None)
    
    study_dates = [activity["activity_date"].strftime("%Y-%m-%d") for activity in activities]
    date_list = [activity["activity_date"].date() for activity in activities]
    
    # 스트릭 계산
    def calculate_streaks(dates):
        if not dates:
            return 0, 0
        
        # 최장 스트릭 계산
        max_streak = 1
        current_temp_streak = 1
        
        for i in range(1, len(dates)):
            if (dates[i] - dates[i-1]).days == 1:
                current_temp_streak += 1
            else:
                current_temp_streak = 1
            max_streak = max(max_streak, current_temp_streak)
        
        # 현재 스트릭 계산 (최근 날짜부터 역순)
        current_streak = 1 if dates else 0
        for i in range(len(dates)-1, 0, -1):
            if (dates[i] - dates[i-1]).days == 1:
                current_streak += 1
            else:
                break
        
        return current_streak, max_streak
    
    current_streak, longest_streak = calculate_streaks(date_list)
    
    return APIResponse.success(data={
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "study_dates": study_dates,
        "total_study_days": len(study_dates)
    })

@user_daily_activity_router.post("/complete")
async def complete_daily_activity(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """일일 활동 완료 처리"""
    user_id = get_current_user_id(request)
    
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 오늘 활동 기록 업데이트
    result = await db.user_daily_activity.update_one(
        {"user_id": ObjectId(user_id), "activity_date": today},
        {
            "$set": {
                "has_activity": True,
                "updated_at": datetime.utcnow()
            }
        },
        upsert=True
    )
    
    return APIResponse.success(message="Daily activity completed")

# =============== 하위 호환성을 위한 deprecated 엔드포인트들 ===============

# 기존 엔드포인트들을 deprecated로 마크하고 새로운 엔드포인트로 리다이렉트
@router.post("/category")
async def create_category_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use POST /learning/categories instead"""
    data = await request.json()
    if "name" not in data or "description" not in data or "order" not in data:
        raise HTTPException(status_code=400, detail="Missing 'name', 'description' or 'order'")
    
    category_data = CategoryCreate(
        name=data["name"],
        description=data["description"],
        order=data["order"]
    )
    return await create_category(category_data, db)

@router.post("/chapter")
async def create_chapter_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use POST /learning/chapters instead"""
    data = await request.json()
    
    if "title" not in data or "description" not in data or "categoryname" not in data or "order" not in data or "type" not in data:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    chapter_data = ChapterCreate(
        title=data["title"],
        description=data["description"],
        category_name=data["categoryname"],
        order=data["order"],
        type=data["type"]
    )
    return await create_chapter(chapter_data, db)

@router.post("/lesson")
async def create_lesson_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use POST /learning/lessons instead"""
    data = await request.json()
    
    if "sign" not in data or "description" not in data or "type" not in data or "order" not in data or "chapter" not in data:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    lesson_data = LessonCreate(
        sign=data["sign"],
        description=data["description"],
        type=data["type"],
        order=data["order"],
        chapter=data["chapter"],
        url=data.get("url", "")
    )
    return await create_lesson(lesson_data, db)

@router.get("/chapter/{category}")
async def get_chapters_deprecated(category: str, request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use GET /learning/categories/{category_id} instead"""
    return await get_category(category, request, db)

# 기존의 복잡한 엔드포인트들은 그대로 유지하되 deprecated 마크 추가
@router.get("/progress/failures-by-username/{username}")
async def get_failed_lessons_by_username_deprecated(username: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated This endpoint will be removed in future versions"""
    # 기존 로직 유지
    user = await db.users.find_one({"nickname": username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_id = user["_id"]
    
    # 실패한 레슨들 조회
    failed_progresses = await db.User_Lesson_Progress.find({
        "user_id": user_id,
        "status": "failed"
    }).to_list(length=None)
    
    failed_lessons = []
    for progress in failed_progresses:
        lesson = await db.Lessons.find_one({"_id": progress["lesson_id"]})
        if lesson:
            failed_lessons.append({
                "lesson_id": str(lesson["_id"]),
                "sign_text": lesson.get("sign_text", ""),
                "content_type": lesson.get("content_type", ""),
                "failed_at": progress.get("updated_at")
            })
    
    return {
        "user_id": str(user_id),
        "username": username,
        "failed_lessons": failed_lessons,
        "total_failed": len(failed_lessons)
    }

@router.post("/progress/category/set")
async def progress_category_set_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use POST /learning/progress/categories instead"""
    # 기존 로직 유지하되 deprecated 마크
    data = await request.json()
    user_id = get_current_user_id(request)
    
    category_id = data.get("categoryId")
    status = data.get("status", "completed")
    
    if not category_id:
        raise HTTPException(status_code=400, detail="categoryId is required")
    
    try:
        category_object_id = ObjectId(category_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid category ID")
    
    # 카테고리 내 모든 레슨 상태 업데이트
    chapters = await db.Chapters.find({"category_id": category_object_id}).to_list(length=None)
    chapter_ids = [chapter["_id"] for chapter in chapters]
    lessons = await db.Lessons.find({"chapter_id": {"$in": chapter_ids}}).to_list(length=None)
    
    for lesson in lessons:
        await db.User_Lesson_Progress.update_one(
            {"user_id": ObjectId(user_id), "lesson_id": lesson["_id"]},
            {
                "$set": {
                    "status": status,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )
    
    return {"message": f"Category progress set to {status}"}

@router.post("/progress/chapter/set")
async def progress_chapter_set_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use POST /learning/progress/chapters instead"""
    # 기존 로직 유지하되 deprecated 마크
    data = await request.json()
    user_id = get_current_user_id(request)
    
    chapter_id = data.get("chapterId")
    status = data.get("status", "completed")
    
    if not chapter_id:
        raise HTTPException(status_code=400, detail="chapterId is required")
    
    try:
        chapter_object_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chapter ID")
    
    # 챕터 내 모든 레슨 상태 업데이트
    lessons = await db.Lessons.find({"chapter_id": chapter_object_id}).to_list(length=None)
    
    for lesson in lessons:
        await db.User_Lesson_Progress.update_one(
            {"user_id": ObjectId(user_id), "lesson_id": lesson["_id"]},
            {
                "$set": {
                    "status": status,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )
    
    return {"message": f"Chapter progress set to {status}"}

# 나머지 복잡한 엔드포인트들은 그대로 유지하되 deprecated 마크만 추가
@router.post("/study/letter")
async def letter_study_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use POST /learning/sessions instead"""
    # 기존 로직 유지
    data = await request.json()
    user_id = get_current_user_id(request)
    
    lesson_id = data.get("lessonId")
    if not lesson_id:
        raise HTTPException(status_code=400, detail="lessonId is required")
    
    try:
        lesson_object_id = ObjectId(lesson_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lesson ID")
    
    # 레슨 조회
    lesson = await db.Lessons.find_one({"_id": lesson_object_id})
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
    # 학습 시작 상태로 업데이트
    await db.User_Lesson_Progress.update_one(
        {"user_id": ObjectId(user_id), "lesson_id": lesson_object_id},
        {
            "$set": {
                "status": "in_progress",
                "started_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        },
        upsert=True
    )
    
    return {
        "lesson_id": str(lesson["_id"]),
        "sign_text": lesson.get("sign_text", ""),
        "content_type": lesson.get("content_type", ""),
        "media_url": lesson.get("media_url", ""),
        "status": "started"
    }

@router.post("/result/letter")
async def letter_result_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use POST /learning/sessions/{session_id}/results instead"""
    # 기존 로직 유지
    data = await request.json()
    user_id = get_current_user_id(request)
    
    lesson_id = data.get("lessonId")
    score = data.get("score", 0)
    is_correct = data.get("isCorrect", False)
    
    if not lesson_id:
        raise HTTPException(status_code=400, detail="lessonId is required")
    
    try:
        lesson_object_id = ObjectId(lesson_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lesson ID")
    
    # 결과 저장
    status = "completed" if is_correct else "failed"
    
    await db.User_Lesson_Progress.update_one(
        {"user_id": ObjectId(user_id), "lesson_id": lesson_object_id},
        {
            "$set": {
                "status": status,
                "score": score,
                "completed_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        },
        upsert=True
    )
    
    # 성공 시 일일 활동 기록
    if is_correct:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        await db.user_daily_activity.update_one(
            {"user_id": ObjectId(user_id), "activity_date": today},
            {
                "$set": {
                    "has_activity": True,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )
    
    return {
        "lesson_id": lesson_id,
        "status": status,
        "score": score,
        "message": "Result saved successfully"
    }

@router.get("/recent-learning")
async def get_recent_learning_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use GET /learning/progress/recent instead"""
    user_id = get_current_user_id(request)
    
    # 최근 학습한 레슨들 조회
    recent_progress = await db.User_Lesson_Progress.find(
        {"user_id": ObjectId(user_id)}
    ).sort("updated_at", -1).limit(10).to_list(length=10)
    
    recent_lessons = []
    for progress in recent_progress:
        lesson = await db.Lessons.find_one({"_id": progress["lesson_id"]})
        if lesson:
            recent_lessons.append({
                "lesson_id": str(lesson["_id"]),
                "sign_text": lesson.get("sign_text", ""),
                "content_type": lesson.get("content_type", ""),
                "status": progress.get("status", ""),
                "score": progress.get("score"),
                "updated_at": progress.get("updated_at")
            })
    
    return {
        "recent_lessons": recent_lessons,
        "total": len(recent_lessons)
    }

@router.get("/progress/overview")
async def get_progress_overview_deprecated(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """@deprecated Use GET /learning/progress instead"""
    return await get_user_progress(request, db)
