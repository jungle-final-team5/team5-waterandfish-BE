from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, status, Cookie
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.session import get_db
from .utils import get_user_id_from_token, require_auth, convert_objectid

def get_utc_today():
    now_utc = datetime.utcnow()
    return datetime.combine(now_utc.date(), datetime.min.time())

router = APIRouter(prefix="/progress", tags=["progress"])


# 오늘 활동 기록 함수
async def mark_today_activity(user_id, db):
    today = get_utc_today()
    await db.user_daily_activity.update_one(
        {"user_id": ObjectId(user_id), "activity_date": today},
        {"$set": {"has_activity": True, "updated_at": datetime.utcnow()}},
        upsert=True
    )

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

    # 챕터 프로그레스가 없으면 생성
    if not existing_progress:
        await db.User_Chapter_Progress.insert_one({
            "user_id": ObjectId(user_id),
            "chapter_id": chapter_obj_id,
            "complete": False,
            "complete_at": None
        })
        message = "챕터 및 레슨 진도 초기화 완료"
        status_code = status.HTTP_201_CREATED
    else:
        message = "이미 초기화된 챕터, 누락된 레슨 진도 추가 완료"
        status_code = status.HTTP_200_OK

    # 하위 레슨 진도도 누락된 것만 추가
    lessons = await db.Lessons.find({"chapter_id": chapter_obj_id}).to_list(length=None)
    lesson_ids = [lesson["_id"] for lesson in lessons]
    # 이미 존재하는 레슨 진도 조회
    existing_lesson_progress = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id),
        "lesson_id": {"$in": lesson_ids}
    }).to_list(length=None)
    existing_lesson_ids = {p["lesson_id"] for p in existing_lesson_progress}
    progress_bulk = []
    for lesson in lessons:
        if lesson["_id"] not in existing_lesson_ids:
            progress_bulk.append({
                "user_id": ObjectId(user_id),
                "lesson_id": lesson["_id"],
                "status": "not_started",
                "updated_at": datetime.utcnow()
            })
    if progress_bulk:
        await db.User_Lesson_Progress.insert_many(progress_bulk)

    return JSONResponse(
        status_code=status_code,
        content={"success": True, "message": message}
    )

# 레슨 이벤트 업데이트
@router.post("/lessons/events")
async def update_lesson_events(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 이벤트 업데이트 (토큰 기반 인증 사용)"""
    user_id = require_auth(request)  # 토큰에서 user_id 추출
    data = await request.json()
    lesson_ids = [ObjectId(lid) for lid in data.get("lesson_ids", [])]
    mode = data.get("mode")  # 예: 'study', 'quiz', 'review'
    update_fields = {"last_event_at": datetime.utcnow()}
    if mode:
        update_fields["last_mode"] = mode
    await db.User_Lesson_Progress.update_many(
        {"user_id": ObjectId(user_id), "lesson_id": {"$in": lesson_ids}},
        {"$set": update_fields}
    )
    # 학습 활동 기록
    await mark_today_activity(user_id, db)
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
            "data": {"category": None, "chapter": None, "chapterId": None, "modeNum": None},
            "message": "최근 학습 없음"
        }
    lesson_id = progress[0]["lesson_id"]
    last_mode = progress[0].get("last_mode") or progress[0].get("status")  # 예시: 'study', 'quiz', 'review'
    lesson = await db.Lessons.find_one({"_id": lesson_id})
    if not lesson:
        return {
            "success": True,
            "data": {"category": None, "chapter": None, "chapterId": None, "modeNum": None},
            "message": "최근 학습 없음"
        }
    chapter = await db.Chapters.find_one({"_id": lesson["chapter_id"]})
    if not chapter:
        return {
            "success": True,
            "data": {"category": None, "chapter": None, "chapterId": None, "modeNum": None},
            "message": "최근 학습 없음"
        }
    category = await db.Category.find_one({"_id": chapter["category_id"]})
    if not category:
        return {
            "success": True,
            "data": {"category": None, "chapter": chapter["title"], "chapterId": str(chapter["_id"]), "modeNum": None},
            "message": "최근 학습 있음"
        }
    # modeNum 매핑
    mode_map = {"study": 1, "quiz": 2, "review": 3}
    mode_num = mode_map.get(last_mode, 1)  # 기본값 1(학습)
    return {
        "success": True,
        "data": {
            "category": category["name"],
            "chapter": chapter["title"],
            "chapterId": str(chapter["_id"]),
            "modeNum": mode_num
        },
        "message": "최근 학습 있음"
    }


# 실패한 레슨 조회 (쿠키/토큰에서 user_id 추출)
@router.get("/failures/me")
async def get_failed_lessons_by_me(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """내 실패한 레슨 조회 (쿠키/토큰 기반)"""
    user_id = require_auth(request)
    # 해당 user_id로 실패한 progress 조회
    failed_progresses = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id),
        "status": "quiz_wrong"
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
    # 각 레슨에 category 이름, word, chapter_title 필드 추가
    for lesson in lessons:
        # chapter 정보 가져오기
        chapter = await db.Chapters.find_one({"_id": lesson["chapter_id"]})
        category = await db.Category.find_one({"_id": chapter["category_id"]}) if chapter else None
        # category 이름 추가
        lesson["category"] = category["name"] if category else "Unknown"
        # word 필드에 sign을 복사
        lesson["word"] = lesson.get("sign_text", "")
        # chapter_title 추가
        lesson["chapter_title"] = chapter["title"] if chapter else ""
    return {
        "success": True,
        "data": convert_objectid(lessons),
        "message": "실패한 레슨 조회 성공"
    }

@router.get("/failures/{chapter_id}")
async def get_failed_lessons_with_chapterId(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """내 실패한 레슨 조회 (챕터ID 기반)"""
    # 1. 사용자 인증
    user_id = require_auth(request)

    # 2. chapter_id 유효성 검사
    try:
        chapter_obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid chapter ID"
        )

    # 3. 해당 챕터의 모든 레슨 조회
    lessons = await db.Lessons.find({"chapter_id": chapter_obj_id}).to_list(length=None)
    if not lessons:
        return {"success": True, "data": [], "message": "실패한 레슨 없음"}

    # 4. progress에서 user_id + lesson_id ∈ lessons + status='quiz_wrong' 필터링
    lesson_ids = [lesson["_id"] for lesson in lessons]
    failed_progress = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id),
        "lesson_id": {"$in": lesson_ids},
        "status": "quiz_wrong"
    }).to_list(length=None)

    # 5. 교집합: lessons 중 progress에 있는 아이디만 남김
    failed_ids = {p["lesson_id"] for p in failed_progress}
    failed_lessons = [lesson for lesson in lessons if lesson["_id"] in failed_ids]
    
    # 각 레슨에 word 필드 추가 (sign_text를 word로 매핑)
    for lesson in failed_lessons:
        lesson["word"] = lesson.get("sign_text", "")
    
    return {
        "success": True,
        "data": convert_objectid(failed_lessons),
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
    # 학습 활동 기록
    await mark_today_activity(user_id, db)
    return {
        "success": True,
        "message": "학습 진행 상태 업데이트 완료"
    }

@router.get("/failures/letter/{chaptertype}")
async def get_failed_lessons_letter(
    chaptertype: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """내 실패한 레슨 조회 (자음/모음 챕터 전체, sign_text 리스트 반환)"""
    user_id = require_auth(request)
    if chaptertype == "consonant":
        chapters = await db.Chapters.find({"title": "자음"}, {"_id": 1}).to_list(length=None)
    elif chaptertype == "vowel":
        chapters = await db.Chapters.find({"title": "모음"}, {"_id": 1}).to_list(length=None)
    else:
        return {"success": False, "data": [], "message": "잘못된 chaptertype"}
    chapter_ids = [c["_id"] for c in chapters]
    if not chapter_ids:
        return {"success": True, "data": [], "message": "해당 챕터 없음"}

    lessons = await db.Lessons.find({"chapter_id": {"$in": chapter_ids}}, {"_id": 1, "sign_text": 1}).to_list(length=None)
    lesson_ids = [l["_id"] for l in lessons]
    lesson_id_to_sign = {l["_id"]: l.get("sign_text", "") for l in lessons}
    if not lesson_ids:
        return {"success": True, "data": [], "message": "해당 레슨 없음"}

    progresses = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id),
        "lesson_id": {"$in": lesson_ids},
        "status": "quiz_wrong"
    }).to_list(length=None)

    failed_signs = [lesson_id_to_sign.get(p["lesson_id"], "") for p in progresses if lesson_id_to_sign.get(p["lesson_id"], "")]
    failed_signs = sorted(list(set(failed_signs)))

    return {
        "success": True,
        "data": failed_signs,
        "message": "실패한 레슨(글자) 조회 성공"
    }


@router.get("/chapters/{chapter_id}/lessons")
async def get_chapter_lessons_progress(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """특정 챕터 내 레슨 학습 진행 상태 조회"""
    user_id = require_auth(request)
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid chapter ID"
        )
    lessons = await db.Lessons.find({"chapter_id": obj_id}).to_list(length=None)
    lesson_ids = [lesson["_id"] for lesson in lessons]
    progress = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id),
        "lesson_id": {"$in": lesson_ids}
    }).to_list(length=None)
    progress_dict = {str(p["lesson_id"]): p for p in progress}
    for lesson in lessons:
        lesson_progress = progress_dict.get(str(lesson["_id"]), {})
        lesson["progress"] = lesson_progress.get("status", "not_started")
    return {
        "success": True,
        "data": convert_objectid(lessons),
        "message": "레슨 학습 진행 상태 조회 성공"
    }

@router.get("/chapters/{chapter_id}/failures")
async def get_chapter_failed_lessons(
    chapter_id: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """특정 챕터 내 틀린(quiz_wrong) 레슨만 반환"""
    user_id = require_auth(request)
    try:
        obj_id = ObjectId(chapter_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid chapter ID"
        )
    # 1. 해당 챕터의 모든 레슨 id 조회
    lessons = await db.Lessons.find({"chapter_id": obj_id}).to_list(length=None)
    lesson_ids = [lesson["_id"] for lesson in lessons]
    if not lesson_ids:
        return {"success": True, "data": [], "message": "해당 챕터에 레슨이 없습니다"}
    # 2. User_Lesson_Progress에서 user_id, lesson_id in (위 id들), status == "quiz_wrong" 필터
    progresses = await db.User_Lesson_Progress.find({
        "user_id": ObjectId(user_id),
        "lesson_id": {"$in": lesson_ids},
        "status": "quiz_wrong"
    }).to_list(length=None)
    progress_map = {p["lesson_id"]: p for p in progresses}
    # 3. 해당 레슨 정보 + 진행상태 반환
    chapter = await db.Chapters.find_one({"_id": obj_id})
    category = await db.Category.find_one({"_id": chapter["category_id"]}) if chapter else None
    failed_lessons = []
    for lesson in lessons:
        p = progress_map.get(lesson["_id"])
        if not p:
            continue
        failed_lessons.append({
            "id": str(lesson["_id"]),
            "word": lesson.get("sign_text", ""),
            "videoUrl": lesson.get("media_url", ""),
            "description": lesson.get("description", ""),
            "status": p.get("status", "not_started"),
            "last_event_at": p.get("last_event_at"),
            "updated_at": p.get("updated_at"),
            "chapter_title": chapter["title"] if chapter else "",
            "category_name": category["name"] if category else "Unknown"
        })
    return {
        "success": True,
        "data": failed_lessons,
        "message": "챕터 내 틀린 레슨 조회 성공"
    }