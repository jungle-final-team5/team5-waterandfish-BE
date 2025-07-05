from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth, convert_objectid

router = APIRouter(prefix="/test", tags=["test"])





# /test/letter/:setType/:qOrs 라우트용
@router.get("/letter/{set_type}/{q_or_s}")
async def get_letter_test(
    set_type: str,
    q_or_s: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """글자 테스트 조회 - /test/letter/:setType/:qOrs 라우트용"""
    user_id = get_user_id_from_token(request)
    
    # set_type에 따라 챕터 찾기
    if set_type == "consonant":
        chapter_title = "자음"
    elif set_type == "vowel":
        chapter_title = "모음"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid set type. Use 'consonant' or 'vowel'"
        )
    
    # q_or_s에 따라 모드 결정 (q: quiz, s: study)
    is_quiz_mode = q_or_s == "q"
    
    chapter = await db.Chapters.find_one({"title": chapter_title})
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"{chapter_title} 챕터를 찾을 수 없습니다"
        )
    
    # 챕터의 모든 레슨 가져오기
    lessons = await db.Lessons.find({"chapter_id": chapter["_id"]}).to_list(length=None)
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
    
    result = {
        "id": str(chapter["_id"]),
        "title": chapter["title"],
        "type": chapter.get("lesson_type", None),
        "set_type": set_type,
        "mode": "quiz" if is_quiz_mode else "study",
        "lessons": lesson_list,
        "order_index": chapter.get("order_index", 0)
    }
    
    return {
        "success": True,
        "data": result,
        "message": "글자 테스트 조회 성공"
    }

# 글자 테스트 결과 제출
@router.post("/letter/{set_type}/submit")
async def submit_letter_test(
    set_type: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """글자 테스트 결과 제출"""
    user_id = require_auth(request)
    data = await request.json()
    
    # set_type에 따라 챕터 찾기
    if set_type == "consonant":
        chapter_title = "자음"
    elif set_type == "vowel":
        chapter_title = "모음"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Invalid set type. Use 'consonant' or 'vowel'"
        )
    
    chapter = await db.Chapters.find_one({"title": chapter_title})
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"{chapter_title} 챕터를 찾을 수 없습니다"
        )
    
    passed_letters = data.get("passed", [])
    failed_letters = data.get("failed", [])
    
    # 모든 레슨 가져오기
    lessons = await db.Lessons.find({"chapter_id": chapter["_id"]}).to_list(length=None)
    
    passed_result = []
    failed_result = []
    
    for lesson in lessons:
        if lesson["sign_text"] in passed_letters:
            passed_result.append(lesson["_id"])
        elif lesson["sign_text"] in failed_letters:
            failed_result.append(lesson["_id"])
    
    # 결과에 따른 상태 업데이트
    if passed_letters and not failed_letters:
        # 모두 정답인 경우
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": passed_result}
            },
            {
                "$set": {
                    "status": "quiz_correct",
                    "updated_at": datetime.utcnow(),
                    "last_event_at": datetime.utcnow()
                }
            }
        )
    elif failed_letters:
        # 오답이 있는 경우
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": passed_result + failed_result}
            },
            {
                "$set": {
                    "status": "quiz_wrong",
                    "updated_at": datetime.utcnow(),
                    "last_event_at": datetime.utcnow()
                }
            }
        )
    elif not passed_letters and not failed_letters:
        # 학습만 한 경우
        lesson_ids = [lesson["_id"] for lesson in lessons]
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": lesson_ids},
                "status": {"$in": ["not_started"]}
            },
            {
                "$set": {
                    "status": "study",
                    "updated_at": datetime.utcnow(),
                    "last_event_at": datetime.utcnow()
                }
            }
        )
    
    return {
        "success": True,
        "data": {
            "passed_count": len(passed_result),
            "failed_count": len(failed_result),
            "total_count": len(passed_result) + len(failed_result)
        },
        "message": "글자 테스트 결과 제출 완료"
    }

# 일반 테스트 페이지용
@router.get("")
async def get_test_page(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """테스트 페이지 조회 - /test 라우트용"""
    # 사용 가능한 테스트 타입들 반환
    test_types = [
        {
            "id": "consonant",
            "title": "자음",
            "description": "자음 학습 및 테스트",
            "url": "/test/letter/consonant/s"
        },
        {
            "id": "vowel", 
            "title": "모음",
            "description": "모음 학습 및 테스트",
            "url": "/test/letter/vowel/s"
        }
    ]
    
    return {
        "success": True,
        "data": {
            "test_types": test_types
        },
        "message": "테스트 페이지 조회 성공"
    } 