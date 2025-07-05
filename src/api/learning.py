# 이 파일은 더 이상 사용되지 않습니다.
# 새로운 RESTful API 구조로 분리되었습니다:
# - categories.py: 카테고리 관련 API
# - chapters.py: 챕터 관련 API  
# - lessons.py: 레슨 관련 API
# - progress.py: 프로그레스 관련 API
# - study.py: 학습/퀴즈 관련 API
# - attendance.py: 출석 관련 API
# - users.py: 사용자별 API
# - utils.py: 공통 유틸리티 함수

from fastapi import APIRouter

router = APIRouter(prefix="/learning", tags=["learning"])

@router.get("/")
async def learning_deprecated():
    """이 엔드포인트는 더 이상 사용되지 않습니다."""
    return {
        "message": "이 API는 더 이상 사용되지 않습니다. 새로운 RESTful API 구조를 사용해주세요.",
        "new_endpoints": {
            "categories": "/categories",
            "chapters": "/chapters", 
            "lessons": "/lessons",
            "progress": "/progress",
            "study": "/study",
            "attendance": "/attendance",
            "users": "/users"
        }
    }
