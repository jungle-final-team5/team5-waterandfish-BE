from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import user_router
from .api.auth import router as auth_router
from .api.learning import router as learning_router
from .api.learning import user_daily_activity_router  # streak API 라우터 추가
from .api.badge import router as badge_router
from .api.search import router as search_router
from .core.config import settings

app = FastAPI(title="Water and Fish API", version="1.0.0")

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Water and Fish API v1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": "2024-01-01T00:00:00Z"}

# API v1 라우터 등록 (통일된 prefix 사용)
app.include_router(user_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(learning_router, prefix="/api/v1")
app.include_router(badge_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(user_daily_activity_router, prefix="/api/v1")

# 하위 호환성을 위한 기존 경로 유지 (단계적 마이그레이션 시 제거 예정)
app.include_router(user_router)
app.include_router(auth_router)
app.include_router(learning_router)
app.include_router(badge_router)
app.include_router(search_router)
app.include_router(user_daily_activity_router) 
