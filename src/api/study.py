from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth

router = APIRouter(prefix="/study", tags=["study"])



# 글자 학습 시작
@router.post("/letters")
async def start_letter_study(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """글자 학습 시작"""
    user_id = require_auth(request)
    data = await request.json()
    checked_letters = data.get("checked", [])
    
    if not checked_letters:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="학습한 글자가 없습니다"
        )
    
    # 자음/모음 챕터 찾기
    if checked_letters[0] == "ㄱ":
        chapter_doc = await db.Chapters.find_one({"title": "자음"})
        if not chapter_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="자음 챕터를 찾을 수 없습니다"
            )
    elif checked_letters[0] == "ㅏ":
        chapter_doc = await db.Chapters.find_one({"title": "모음"})
        if not chapter_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="모음 챕터를 찾을 수 없습니다"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="지원하지 않는 글자 타입입니다"
        )
    
    chapter_id = chapter_doc["_id"]
    letters = await db.Lessons.find({"chapter_id": chapter_id}).to_list(length=None)
    letter_ids = [lesson["_id"] for lesson in letters]

    # User_Lesson_Progress에서 not_started만 study로 변경
    await db.User_Lesson_Progress.update_many(
        {
            "user_id": ObjectId(user_id),
            "lesson_id": {"$in": letter_ids},
            "status": "not_started"
        },
        {"$set": {"status": "study", "updated_at": datetime.utcnow()}}
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED, 
        content={"success": True, "message": "study started"}
    )

# 글자 퀴즈 결과
@router.post("/letters/result")
async def submit_letter_quiz_result(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """글자 퀴즈 결과 제출"""
    user_id = require_auth(request)
    data = await request.json()
    
    passed_letters = data.get("passed", [])
    failed_letters = data.get("failed", [])
    
    # 자음/모음 챕터 찾기
    if (passed_letters and passed_letters[0] == 'ㄱ') or (failed_letters and failed_letters[0] == 'ㄱ'):
        chapter_doc = await db.Chapters.find_one({"title": "자음"})
        if not chapter_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="자음 챕터를 찾을 수 없습니다"
            )
    elif (passed_letters and passed_letters[0] == 'ㅏ') or (failed_letters and failed_letters[0] == 'ㅏ'):
        chapter_doc = await db.Chapters.find_one({"title": "모음"})
        if not chapter_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="모음 챕터를 찾을 수 없습니다"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="지원하지 않는 글자 타입입니다"
        )
    
    chapter_id = chapter_doc["_id"]
    passed_result = []
    failed_result = []
    
    letters = await db.Lessons.find({"chapter_id": chapter_id}).to_list(length=None)
    
    for letter in letters:
        if letter["sign_text"] in passed_letters:
            passed_result.append(letter["_id"])
        elif letter["sign_text"] in failed_letters:
            failed_result.append(letter["_id"])
    
    # 맞은 것은 quiz_correct, 틀린 것은 quiz_wrong으로 각각 따로 처리
    if passed_result:
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": passed_result}
            },
            {"$set": {"status": "quiz_correct", "updated_at": datetime.utcnow()}}
        )
    if failed_result:
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": failed_result}
            },
            {"$set": {"status": "quiz_wrong", "updated_at": datetime.utcnow()}}
        )
    if not passed_letters and not failed_letters:
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": [lesson["_id"] for lesson in letters]},
                "status": {"$in": ["not_started"]}
            },
            {"$set": {"status": "study", "updated_at": datetime.utcnow()}}
        )

    return {
        "success": True,
        "data": {"passed": len(passed_result), "failed": len(failed_result)},
        "message": "글자 퀴즈 결과 기록 완료"
    }

# 세션 학습 시작
@router.post("/sessions")
async def start_session_study(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """세션 학습 시작"""
    user_id = require_auth(request)
    data = await request.json()
    lesson_ids = [ObjectId(lesson_id) for lesson_id in data]
    
    # 학습 완료 처리: status를 'study', updated_at을 현재로 업데이트
    await db.User_Lesson_Progress.update_many(
        {
            "user_id": ObjectId(user_id),
            "lesson_id": {"$in": lesson_ids}
        },
        {"$set": {"status": "study", "updated_at": datetime.utcnow()}}
    )
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, 
        content={"success": True, "message": "study started"}
    )

# 세션 퀴즈 결과
@router.post("/sessions/result")
async def submit_session_quiz_result(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """세션 퀴즈 결과 제출"""
    user_id = require_auth(request)
    data = await request.json()
    
    correct_ids = []
    wrong_ids = []
    
    for result in data:
        sign_id = ObjectId(result.get("signId"))
        correct = result.get("correct")
        if correct:
            correct_ids.append(sign_id)
        else:
            wrong_ids.append(sign_id)
    
    # 모두 정답이면 quiz_correct, 하나라도 오답이면 quiz_wrong
    if correct_ids and not wrong_ids:
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": correct_ids}
            },
            {"$set": {"status": "quiz_correct", "updated_at": datetime.utcnow()}}
        )
    elif wrong_ids:
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "lesson_id": {"$in": correct_ids + wrong_ids}
            },
            {"$set": {"status": "quiz_wrong", "updated_at": datetime.utcnow()}}
        )
    elif not data:
        await db.User_Lesson_Progress.update_many(
            {
                "user_id": ObjectId(user_id),
                "status": {"$in": ["not_started"]}
            },
            {"$set": {"status": "study", "updated_at": datetime.utcnow()}}
        )
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, 
        content={"success": True, "message": "quiz complete"}
    ) 

@router.post("/sessions/complete")
async def complete_chapter_study(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """챕터 학습 완료 시 user.chapter_current_index를 +1 (중복 증가 방지)"""
    user_id = require_auth(request)
    data = await request.json()
    chapter_id = data.get("chapter_id")
    if not chapter_id:
        raise HTTPException(status_code=400, detail="chapter_id is required")
    try:
        chapter_obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid chapter_id")
    chapter = await db.Chapters.find_one({"_id": chapter_obj_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    chapter_order = chapter.get("order_index", 0)
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    current_index = user.get("chapter_current_index", 0)
    # 중복 증가 방지: 현재 인덱스와 챕터 order_index가 같을 때만 +1
    if current_index == chapter_order:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"chapter_current_index": 1}}
        )
        updated = True
    else:
        updated = False
    return {
        "success": True,
        "updated": updated,
        "chapter_current_index": current_index + 1 if updated else current_index,
        "message": "챕터 학습 완료 처리 및 다음 챕터 오픈" if updated else "이미 다음 챕터가 열려 있음"
    }
@router.post("/sessions/complete/letter")
async def complete_chapter_study(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)):
    """챕터 학습 완료 시 user.chapter_current_index를 +1 (중복 증가 방지)"""
    user_id = require_auth(request)
    data = await request.json()
    chapter_name = data.get("lettertype")
    if not chapter_name:
        raise HTTPException(status_code=400, detail="chapter_id is required")
    # try:
    #     chapter_obj_id = ObjectId(chapter_id)
    # except Exception:
    #     raise HTTPException(status_code=400, detail="Invalid chapter_id")
    chapter = await db.Chapters.find_one({"title": chapter_name})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    chapter_order = chapter.get("order_index", 0)
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    current_index = user.get("chapter_current_index", 0)
    # 중복 증가 방지: 현재 인덱스와 챕터 order_index가 같을 때만 +1
    if current_index == chapter_order:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"chapter_current_index": 1}}
        )
        updated = True
    else:
        updated = False
    return {
        "success": True,
        "updated": updated,
        "chapter_current_index": current_index + 1 if updated else current_index,
        "message": "챕터 학습 완료 처리 및 다음 챕터 오픈" if updated else "이미 다음 챕터가 열려 있음"
    }