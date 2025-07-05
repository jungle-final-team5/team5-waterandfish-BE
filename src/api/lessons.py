from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, convert_objectid

router = APIRouter(prefix="/lessons", tags=["lessons"])

LESSON_TYPE = ["letter", "word", "sentence"]



@router.post("")
async def create_lesson(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """레슨 생성"""
    data = await request.json()
    
    if "sign" not in data or "description" not in data or "type" not in data or "order" not in data or "chapter" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing required fields: sign, description, type, order, chapter"
        )
    
    if data["type"] not in LESSON_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid type: {data['type']}"
        )
    
    chapter = await db.Chapters.find_one({"title": data["chapter"]})
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Chapter not found"
        )
    
    lesson_data = {
        "chapter_id": chapter["_id"],
        "sign_text": data["sign"],
        "description": data["description"],
        "content_type": data["type"],
        "media_url": data.get("url"),
        "model_data_url": None,
        "order_index": data["order"],
        "created_at": datetime.utcnow()
    }
    
    result = await db.Lessons.insert_one(lesson_data)
    created = await db.Lessons.find_one({"_id": result.inserted_id})
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=convert_objectid(created)
    )

@router.get("")
async def get_all_lessons(db: AsyncIOMotorDatabase = Depends(get_db)):
    """모든 레슨 조회"""
    lessons = await db.Lessons.find().to_list(length=None)
    transformed = [{
        "id": str(lesson["_id"]),
        "chapterId": str(lesson["chapter_id"]),
        "word": lesson.get("sign_text", ""),
        "type": lesson.get("content_type", "")
    } for lesson in lessons]
    
    return {
        "success": True,
        "data": {"lessons": transformed},
        "message": "레슨 목록 조회 성공"
    }

@router.get("/{lesson_id}")
async def get_lesson(
    lesson_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """특정 레슨 조회"""
    try:
        obj_id = ObjectId(lesson_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid lesson ID"
        )
    
    lesson = await db.Lessons.find_one({"_id": obj_id})
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Lesson not found"
        )
    
    return {
        "success": True,
        "data": convert_objectid(lesson),
        "message": "레슨 조회 성공"
    }

@router.put("/{lesson_id}")
async def update_lesson(
    lesson_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 수정"""
    data = await request.json()
    
    try:
        obj_id = ObjectId(lesson_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid lesson ID"
        )
    
    update_data = {}
    if "sign" in data:
        update_data["sign_text"] = data["sign"]
    if "description" in data:
        update_data["description"] = data["description"]
    if "type" in data:
        if data["type"] not in LESSON_TYPE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Invalid type: {data['type']}"
            )
        update_data["content_type"] = data["type"]
    if "url" in data:
        update_data["media_url"] = data["url"]
    if "order" in data:
        update_data["order_index"] = data["order"]
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="No fields to update"
        )
    
    result = await db.Lessons.update_one(
        {"_id": obj_id},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Lesson not found"
        )
    
    return {
        "success": True,
        "message": "레슨 수정 성공"
    }

@router.delete("/{lesson_id}")
async def delete_lesson(
    lesson_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 삭제"""
    try:
        obj_id = ObjectId(lesson_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid lesson ID"
        )
    
    result = await db.Lessons.delete_one({"_id": obj_id})
    
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Lesson not found"
        )
    
    return {
        "success": True,
        "message": "레슨 삭제 성공"
    } 