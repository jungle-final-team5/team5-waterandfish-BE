from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, convert_objectid

router = APIRouter(prefix="/category", tags=["category"])


@router.get("/list")
async def get_categories_list(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """카테고리 목록만 조회 - 성능 최적화용"""
    categories = await db.Category.find().sort("order", 1).to_list(length=None)
    
    results = []
    for category in categories:
        # 각 카테고리의 챕터 개수 조회
        chapter_count = await db.Chapters.count_documents({"category_id": category["_id"]})
        
        results.append({
            "id": str(category["_id"]),
            "title": category["name"],
            "description": category["description"],
            "chapter_count": chapter_count,
            "icon": "📚",
            "emoji": category.get("emoji", "📚"),
            "order_index": category.get("order", category.get("order_index", 0))
        })
    
    return {
        "success": True,
        "data": results or [],
        "message": "카테고리 목록 조회 성공"
    }


@router.post("")
async def create_category(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """카테고리 생성"""
    data = await request.json()
    
    if "title" not in data or "description" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing required fields: title, description"
        )
    
    category_data = {
        "name": data["title"],
        "description": data["description"],
        "order": 0,
        "created_at": datetime.utcnow()
    }
    
    result = await db.Category.insert_one(category_data)
    created = await db.Category.find_one({"_id": result.inserted_id})
    
    if "created_at" in created:
        del created["created_at"]
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=convert_objectid(created)
    )

@router.get("")
async def get_categories(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """모든 카테고리 조회 (챕터와 레슨 포함) - /category 라우트용"""
    user_id = get_user_id_from_token(request)
    print('[get_categories] user_id:', user_id)
    categories = await db.Category.find().to_list(length=None)
    results = []
    
    for category in categories:
        category_id = category["_id"]
        chapters = await db.Chapters.find({"category_id": category_id}).to_list(length=None)
        chapter_list = []
        
        for chapter in chapters:
            chapter_id = chapter["_id"]
            lessons = await db.Lessons.find({"chapter_id": chapter_id}).to_list(length=None)
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
                    "category": category["name"],
                    "difficulty": "medium",
                    "videoUrl": str(lesson.get("media_url", "")),
                    "description": lesson.get("description", ""),
                    "status": lesson_status_map.get(str(lesson["_id"]), "not_started")
                })
            
            chapter_list.append({
                "id": str(chapter["_id"]),
                "title": chapter["title"],
                "type": chapter.get("type", None),
                "lessons": lesson_list,
                "categoryId": str(category_id),
                "order_index": chapter.get("order", chapter.get("order_index", 0))
            })
        
        results.append({
            "id": str(category["_id"]),
            "title": category["name"],
            "description": category["description"],
            "chapters": chapter_list,
            "icon": "📚",
            "emoji": category.get("emoji", "📚"),
            "order_index": category.get("order", category.get("order_index", 0))
        })
    
    return {
        "success": True,
        "data": results or [],
        "message": "카테고리 목록 조회 성공"
    }

@router.get("/{category_id}/chapters")
async def get_category_chapters(
    category_id: str, 
    request: Request, 
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """특정 카테고리의 챕터들 조회 - /category/:categoryId/chapters 라우트용"""
    user_id = get_user_id_from_token(request)
    
    try:
        obj_id = ObjectId(category_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid category ID"
        )
    
    category = await db.Category.find_one({"_id": obj_id})
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Category not found"
        )
    
    chapters = await db.Chapters.find({"category_id": obj_id}).to_list(length=None)
    chapter_list = []
    
    for chapter in chapters:
        chapter_id = chapter["_id"]
        lessons = await db.Lessons.find({"chapter_id": chapter_id}).to_list(length=None)
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
                "category": category["name"],
                "difficulty": "medium",
                "videoUrl": str(lesson.get("media_url", "")),
                "description": lesson.get("description", ""),
                "status": lesson_status_map.get(str(lesson["_id"]), "not_started")
            })
        
        chapter_list.append({
            "id": str(chapter["_id"]),
            "title": chapter["title"],
            "type": chapter.get("type", None),
            "signs": lesson_list,
            "categoryId": str(obj_id),
            "order_index": chapter.get("order", chapter.get("order_index", 0))
        })
    
    result = {
        "id": str(category["_id"]),
        "title": category["name"],
        "description": category["description"],
        "chapters": chapter_list,
        "icon": "📚",
        "order_index": category.get("order", category.get("order_index", 0))
    }
    
    return {
        "success": True,
        "data": result,
        "message": "카테고리 챕터 조회 성공"
    }

@router.put("/{category_id}")
async def update_category(
    category_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """카테고리 수정"""
    data = await request.json()
    
    try:
        obj_id = ObjectId(category_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid category ID"
        )
    
    update_data = {}
    if "title" in data:
        update_data["name"] = data["title"]
    if "description" in data:
        update_data["description"] = data["description"]
    if "order" in data:
        update_data["order"] = data["order"]
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="No fields to update"
        )
    
    result = await db.Category.update_one(
        {"_id": obj_id},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Category not found"
        )
    
    return {
        "success": True,
        "message": "카테고리 수정 성공"
    }

@router.delete("/{category_id}")
async def delete_category(
    category_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """카테고리 삭제"""
    try:
        obj_id = ObjectId(category_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid category ID"
        )
    
    # 연관된 챕터와 레슨도 함께 삭제
    chapters = await db.Chapters.find({"category_id": obj_id}).to_list(length=None)
    chapter_ids = [chapter["_id"] for chapter in chapters]
    
    if chapter_ids:
        # await db.Lessons.delete_many({"chapter_id": {"$in": chapter_ids}})
        await db.Chapters.delete_many({"category_id": obj_id})
    
    result = await db.Category.delete_one({"_id": obj_id})
    
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Category not found"
        )
    
    return {
        "success": True,
        "message": "카테고리 삭제 성공"
    } 