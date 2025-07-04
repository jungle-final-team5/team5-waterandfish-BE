from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth, convert_objectid
import random

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/random-sign")
async def get_random_sign(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """랜덤 수어 추천 - content_type이 'letter'가 아닌 수어 중에서 랜덤 선택"""
    user_id = get_user_id_from_token(request)
    
    # content_type이 "letter"가 아닌 모든 수어 조회
    pipeline = [
        {
            "$match": {
                "content_type": {"$ne": "letter"}
            }
        },
        {
            "$lookup": {
                "from": "Chapters",
                "localField": "chapter_id",
                "foreignField": "_id",
                "as": "chapter"
            }
        },
        {
            "$unwind": "$chapter"
        },
        {
            "$lookup": {
                "from": "Category",
                "localField": "chapter.category_id",
                "foreignField": "_id",
                "as": "category"
            }
        },
        {
            "$unwind": "$category"
        },
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "word": "$sign_text",
                "description": "$description",
                "videoUrl": "$media_url",
                "difficulty": "$difficulty",
                "content_type": "$content_type",
                "chapter": {
                    "id": {"$toString": "$chapter._id"},
                    "title": "$chapter.title",
                    "type": "$chapter.lesson_type"
                },
                "category": {
                    "id": {"$toString": "$category._id"},
                    "name": "$category.name"
                }
            }
        }
    ]
    
    lessons = await db.Lessons.aggregate(pipeline).to_list(length=None)
    
    if not lessons:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="추천할 수어가 없습니다"
        )
    
    # 랜덤으로 하나 선택
    random_lesson = random.choice(lessons)
    
    # 사용자의 학습 진행 상태 확인 (로그인한 경우)
    if user_id:
        progress = await db.User_Lesson_Progress.find_one({
            "user_id": ObjectId(user_id),
            "lesson_id": ObjectId(random_lesson["id"])
        })
        
        if progress:
            random_lesson["status"] = progress.get("status", "not_started")
            random_lesson["last_event_at"] = progress.get("last_event_at")
        else:
            random_lesson["status"] = "not_started"
            random_lesson["last_event_at"] = None
    else:
        random_lesson["status"] = "not_started"
        random_lesson["last_event_at"] = None
    
    # ObjectId를 문자열로 변환
    random_lesson = convert_objectid(random_lesson)

    # word 필드가 string이 아닐 경우 string으로 변환
    if "word" in random_lesson and not isinstance(random_lesson["word"], str):
        random_lesson["word"] = str(random_lesson["word"])
    
    return {
        "success": True,
        "data": {
            "lesson": random_lesson,
            "recommendation_type": "random",
            "reason": "오늘의 랜덤 수어 추천"
        },
        "message": "랜덤 수어 추천 성공"
    }


@router.get("/daily-sign")
async def get_daily_sign(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """오늘의 수어 추천 - 날짜 기반으로 일관된 랜덤 수어"""
    user_id = get_user_id_from_token(request)
    
    # 오늘 날짜를 시드로 사용하여 일관된 랜덤 선택
    today = datetime.utcnow().date()
    seed = today.year * 10000 + today.month * 100 + today.day
    random.seed(seed)
    
    # content_type이 "letter"가 아닌 모든 수어 조회
    pipeline = [
        {
            "$match": {
                "content_type": {"$ne": "letter"}
            }
        },
        {
            "$lookup": {
                "from": "Chapters",
                "localField": "chapter_id",
                "foreignField": "_id",
                "as": "chapter"
            }
        },
        {
            "$unwind": "$chapter"
        },
        {
            "$lookup": {
                "from": "Category",
                "localField": "chapter.category_id",
                "foreignField": "_id",
                "as": "category"
            }
        },
        {
            "$unwind": "$category"
        },
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "word": "$sign_text",
                "description": "$description",
                "videoUrl": "$media_url",
                "difficulty": "$difficulty",
                "content_type": "$content_type",
                "chapter": {
                    "id": {"$toString": "$chapter._id"},
                    "title": "$chapter.title",
                    "type": "$chapter.lesson_type"
                },
                "category": {
                    "id": {"$toString": "$category._id"},
                    "name": "$category.name"
                }
            }
        }
    ]
    
    lessons = await db.Lessons.aggregate(pipeline).to_list(length=None)
    
    if not lessons:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="추천할 수어가 없습니다"
        )
    
    # 날짜 기반 랜덤 선택
    random_lesson = random.choice(lessons)
    
    # 사용자의 학습 진행 상태 확인 (로그인한 경우)
    if user_id:
        progress = await db.User_Lesson_Progress.find_one({
            "user_id": ObjectId(user_id),
            "lesson_id": ObjectId(random_lesson["id"])
        })
        
        if progress:
            random_lesson["status"] = progress.get("status", "not_started")
            random_lesson["last_event_at"] = progress.get("last_event_at")
        else:
            random_lesson["status"] = "not_started"
            random_lesson["last_event_at"] = None
    else:
        random_lesson["status"] = "not_started"
        random_lesson["last_event_at"] = None
    
    # ObjectId를 문자열로 변환
    random_lesson = convert_objectid(random_lesson)

    # word 필드가 string이 아닐 경우 string으로 변환
    if "word" in random_lesson and not isinstance(random_lesson["word"], str):
        random_lesson["word"] = str(random_lesson["word"])
    
    return {
        "success": True,
        "data": {
            "lesson": random_lesson,
            "recommendation_type": "daily",
            "date": today.isoformat(),
            "reason": f"{today.strftime('%Y년 %m월 %d일')} 오늘의 수어"
        },
        "message": "오늘의 수어 추천 성공"
    }


@router.get("/popular-signs")
async def get_popular_signs(
    request: Request,
    limit: int = 5,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """인기 수어 추천 - 학습 완료율이 높은 수어들"""
    user_id = get_user_id_from_token(request)
    
    # content_type이 "letter"가 아닌 수어 중에서 학습 완료율이 높은 순으로 정렬
    pipeline = [
        {
            "$match": {
                "content_type": {"$ne": "letter"}
            }
        },
        {
            "$lookup": {
                "from": "User_Lesson_Progress",
                "localField": "_id",
                "foreignField": "lesson_id",
                "as": "progresses"
            }
        },
        {
            "$addFields": {
                "completed_count": {
                    "$size": {
                        "$filter": {
                            "input": "$progresses",
                            "cond": {"$eq": ["$$this.status", "completed"]}
                        }
                    }
                },
                "total_attempts": {"$size": "$progresses"}
            }
        },
        {
            "$lookup": {
                "from": "Chapters",
                "localField": "chapter_id",
                "foreignField": "_id",
                "as": "chapter"
            }
        },
        {
            "$unwind": "$chapter"
        },
        {
            "$lookup": {
                "from": "Category",
                "localField": "chapter.category_id",
                "foreignField": "_id",
                "as": "category"
            }
        },
        {
            "$unwind": "$category"
        },
        {
            "$project": {
                "id": {"$toString": "$_id"},
                "word": "$sign_text",
                "description": "$description",
                "videoUrl": "$media_url",
                "difficulty": "$difficulty",
                "content_type": "$content_type",
                "completed_count": 1,
                "total_attempts": 1,
                "completion_rate": {
                    "$cond": [
                        {"$eq": ["$total_attempts", 0]},
                        0,
                        {"$divide": ["$completed_count", "$total_attempts"]}
                    ]
                },
                "chapter": {
                    "id": {"$toString": "$chapter._id"},
                    "title": "$chapter.title",
                    "type": "$chapter.lesson_type"
                },
                "category": {
                    "id": {"$toString": "$category._id"},
                    "name": "$category.name"
                }
            }
        },
        {
            "$sort": {"completion_rate": -1, "total_attempts": -1}
        },
        {
            "$limit": limit
        }
    ]
    
    lessons = await db.Lessons.aggregate(pipeline).to_list(length=None)
    
    if not lessons:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="인기 수어가 없습니다"
        )
    
    # 사용자의 학습 진행 상태 확인 (로그인한 경우)
    if user_id:
        lesson_ids = [ObjectId(lesson["id"]) for lesson in lessons]
        progresses = await db.User_Lesson_Progress.find({
            "user_id": ObjectId(user_id),
            "lesson_id": {"$in": lesson_ids}
        }).to_list(length=None)
        
        progress_map = {str(p["lesson_id"]): p for p in progresses}
        
        for lesson in lessons:
            progress = progress_map.get(lesson["id"], {})
            lesson["status"] = progress.get("status", "not_started")
            lesson["last_event_at"] = progress.get("last_event_at")
    else:
        for lesson in lessons:
            lesson["status"] = "not_started"
            lesson["last_event_at"] = None
    
    # ObjectId를 문자열로 변환
    lessons = [convert_objectid(lesson) for lesson in lessons]

    # word 필드가 string이 아닐 경우 string으로 변환
    for lesson in lessons:
        if "word" in lesson and not isinstance(lesson["word"], str):
            lesson["word"] = str(lesson["word"])
    
    return {
        "success": True,
        "data": {
            "lessons": lessons,
            "recommendation_type": "popular",
            "reason": "다른 사용자들이 많이 완료한 수어들"
        },
        "message": "인기 수어 추천 성공"
    } 