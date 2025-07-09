from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, convert_objectid

router = APIRouter(prefix="/chapters", tags=["chapters"])

CHAPTER_TYPES = ["word", "sentence"]



@router.post("")
async def create_chapter(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """챕터 생성"""
    data = await request.json()
    
    if "title" not in data or "categoryid" not in data or "type" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing required fields: title, categoryid, type"
        )
    
    if data["type"] not in CHAPTER_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid type: {data['type']}"
        )
    
    try:
        category_id = ObjectId(data["categoryid"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid category ID"
        )
    
    category = await db.Category.find_one({"_id": category_id})
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Category not found"
        )
    
    chapter_data = {
        "category_id": category["_id"],
        "title": data["title"],
        "lesson_type": data["type"],
        "order_index": 0,
        "description": None,
        "created_at": datetime.utcnow()
    }
    
    result = await db.Chapters.insert_one(chapter_data)
    created = await db.Chapters.find_one({"_id": result.inserted_id})
    created.pop("created_at", None)
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=convert_objectid(created)
    )

@router.get("")
async def get_all_chapters(db: AsyncIOMotorDatabase = Depends(get_db)):
    """모든 챕터 조회"""
    chapters = await db.Chapters.find().to_list(length=None)
    
    return {
        "success": True,
        "data": {"chapters": convert_objectid(chapters)},
        "message": "챕터 목록 조회 성공"
    }

@router.get("/{chapter_id}")
async def get_chapter(
    chapter_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """특정 챕터 조회"""
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    print('[get_chapter] chapter_id:', chapter_id)
    chapter = await db.Chapters.find_one({"_id": obj_id})
    print('[get_chapter] chapter:', chapter)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Chapter not found"
        )
    
    return {
        "success": True,
        "data": {"type": chapter.get("title", "기타")},
        "message": "챕터 조회 성공"
    }

@router.put("/{chapter_id}")
async def update_chapter(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 수정"""
    data = await request.json()
    
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    update_data = {}
    if "title" in data:
        update_data["title"] = data["title"]
    if "type" in data:
        if data["type"] not in CHAPTER_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Invalid type: {data['type']}"
            )
        update_data["lesson_type"] = data["type"]
    if "description" in data:
        update_data["description"] = data["description"]
    if "order_index" in data:
        update_data["order_index"] = data["order_index"]
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="No fields to update"
        )
    
    result = await db.Chapters.update_one(
        {"_id": obj_id},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Chapter not found"
        )
    
    return {
        "success": True,
        "message": "챕터 수정 성공"
    }

@router.delete("/{chapter_id}")
async def delete_chapter(
    chapter_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 삭제"""
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    # 연관된 레슨도 함께 삭제
    # await db.Lessons.delete_many({"chapter_id": obj_id})
    
    result = await db.Chapters.delete_one({"_id": obj_id})
    
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Chapter not found"
        )
    
    return {
        "success": True,
        "message": "챕터 삭제 성공"
    }

@router.post("/{chapter_id}/lessons/connect")
async def connect_lessons_to_chapter(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터에 레슨 연결"""
    data = await request.json()
    
    try:
        chapter_obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid chapter ID"
        )
    
    lesson_ids = data.get("lesson", [])
    lesson_obj_ids = [ObjectId(lid) for lid in lesson_ids]
    
    # 기존 연결 해제
    await db.Lessons.update_many(
        {"chapter_id": chapter_obj_id},
        {"$set": {"chapter_id": None}}
    )
    
    # 새로운 연결 설정
    if lesson_obj_ids:
        await db.Lessons.update_many(
            {"_id": {"$in": lesson_obj_ids}},
            {"$set": {"chapter_id": chapter_obj_id}}
        )
    
    return {
        "success": True,
        "message": "레슨 연결 성공"
    }

@router.get("/{chapter_id}/session")
async def get_chapter_session(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 학습 세션 조회 - /chapters/{chapter_id}/session"""
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

@router.get("/{chapter_id}/guide")
async def get_chapter_guide(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """챕터 학습 가이드 조회 - /chapters/{chapter_id}/guide"""
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
    category = await db.Category.find_one({"_id": chapter["category_id"]})
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