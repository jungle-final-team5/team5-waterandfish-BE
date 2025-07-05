from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import user_router
from .api.auth import router as auth_router
from .api.learning import router as learning_router
from .api.categories import router as categories_router
from .api.chapters import router as chapters_router
from .api.lessons import router as lessons_router
from .api.progress import router as progress_router
from .api.study import router as study_router
from .api.attendance import router as attendance_router
from .api.users import router as users_router
from .api.learn import router as learn_router
from .api.quiz import router as quiz_router
from .api.test import router as test_router
from .api.review import router as review_router
from .api.badge import router as badge_router
from .api.search import router as search_router
from .core.config import settings

app = FastAPI(
    title="Water and Fish API",
    description="수어 학습 플랫폼 API",
    version="1.0.0"
)

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,  # 리스트로 넘겨야 함!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello, team5-waterandfish-BE!"}

# 프론트엔드 라우트에 맞춘 새로운 API 라우터들
app.include_router(categories_router)  # /category
app.include_router(learn_router)       # /learn
app.include_router(quiz_router)        # /quiz
app.include_router(test_router)        # /test
app.include_router(review_router)      # /review

# 기존 RESTful API 라우터들 (하위 호환성)
app.include_router(chapters_router)
app.include_router(lessons_router)
app.include_router(progress_router)
app.include_router(study_router)
app.include_router(attendance_router)
app.include_router(users_router)

# 기존 라우터들 (하위 호환성)
app.include_router(user_router)
app.include_router(auth_router)
app.include_router(learning_router)  # deprecated
app.include_router(badge_router)
app.include_router(search_router)

