# src/api/search.py
from fastapi import APIRouter, Query, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from ..services.embedding import embed
from ..core.config import settings
from ..core.auth import APIResponse
from ..db.session import get_db
from typing import Optional, List, Dict, Any

router = APIRouter(prefix="/search", tags=["search"])

@router.get("/health")
async def search_health():
    """검색 서비스 상태 확인"""
    return APIResponse.success(message="Search service is healthy")

def get_projection() -> Dict[str, Any]:
    """검색 결과 프로젝션"""
    return {
        "_id": 0,
        "sign_text": 1,
        "lesson_id": 1,
        "chapter_id": 1,
        "content_type": 1,
        "description": 1,
        "media_url": 1,
        "score": {"$meta": "vectorSearchScore"}
    }

def get_post_filter() -> Dict[str, Any]:
    """검색 필터"""
    return {
        "$and": [
            {"content_type": {"$ne": "letter"}},      # letter 제외
            {"sign_text": {"$type": "string"}},       # 문자열만
            {"sign_text": {"$regex": "[^0-9]"}}       # 숫자-only 제외
        ]
    }

@router.get("/lessons")
async def search_lessons(
    q: str = Query(..., min_length=1, max_length=100, description="검색어"),
    limit: int = Query(default=10, ge=1, le=50, description="결과 수 제한"),
    offset: int = Query(default=0, ge=0, description="결과 시작 위치"),
    content_type: Optional[str] = Query(default=None, description="컨텐츠 타입 필터"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 검색 (벡터 검색 + 텍스트 검색)"""
    
    try:
        # 벡터 검색 시도
        q_vec = embed(q.strip())
        
        # 필터 설정
        post_filter = get_post_filter()
        if content_type:
            post_filter["$and"].append({"content_type": content_type})
        
        # 벡터 검색 파이프라인
        vector_pipeline = [
            {
                "$vectorSearch": {
                    "index": "waterandfish_lessons",
                    "path": "embedding",
                    "queryVector": q_vec,
                    "limit": limit + offset,
                    "numCandidates": (limit + offset) * 5
                }
            },
            {"$match": post_filter},
            {"$skip": offset},
            {"$limit": limit},
            {"$project": get_projection()}
        ]
        
        hits = await db.Lessons.aggregate(vector_pipeline).to_list(length=limit)
        
        # 벡터 검색 결과가 없으면 텍스트 검색 시도
        if not hits:
            text_filter = {
                **post_filter,
                "sign_text": {"$regex": f".*{q.strip()}.*", "$options": "i"}
            }
            
            hits = await db.Lessons.find(
                text_filter,
                get_projection()
            ).skip(offset).limit(limit).to_list(length=limit)
        
        # 결과 가공
        results = []
        for hit in hits:
            result_item = {
                "lesson_id": hit.get("lesson_id"),
                "sign_text": hit.get("sign_text"),
                "content_type": hit.get("content_type"),
                "description": hit.get("description", ""),
                "media_url": hit.get("media_url", ""),
                "relevance_score": hit.get("score", 0)
            }
            results.append(result_item)
        
        return APIResponse.success(data={
            "query": q,
            "results": results,
            "total": len(results),
            "offset": offset,
            "limit": limit,
            "search_type": "vector_search" if results and results[0].get("relevance_score", 0) > 0.5 else "text_search"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.get("/lessons/suggest")
async def suggest_lessons(
    q: str = Query(..., min_length=1, max_length=50, description="검색어"),
    limit: int = Query(default=5, ge=1, le=10, description="제안 수 제한"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """레슨 자동완성 제안"""
    
    try:
        # 접두사 매칭으로 자동완성 제안
        suggestions = await db.Lessons.find(
            {
                "$and": [
                    {"sign_text": {"$regex": f"^{q.strip()}", "$options": "i"}},
                    {"content_type": {"$ne": "letter"}},
                    {"sign_text": {"$type": "string"}},
                    {"sign_text": {"$regex": "[^0-9]"}}
                ]
            },
            {
                "_id": 0,
                "sign_text": 1,
                "content_type": 1
            }
        ).limit(limit).to_list(length=limit)
        
        # 중복 제거 및 정렬
        unique_suggestions = []
        seen = set()
        
        for suggestion in suggestions:
            sign_text = suggestion.get("sign_text", "")
            if sign_text and sign_text not in seen:
                seen.add(sign_text)
                unique_suggestions.append({
                    "text": sign_text,
                    "type": suggestion.get("content_type", "")
                })
        
        return APIResponse.success(data={
            "query": q,
            "suggestions": unique_suggestions,
            "total": len(unique_suggestions)
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Suggestion failed: {str(e)}")

@router.get("/lessons/popular")
async def get_popular_searches(
    limit: int = Query(default=10, ge=1, le=20, description="인기 검색어 수"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """인기 검색어 조회"""
    
    try:
        # 가장 많이 학습된 레슨들을 인기 검색어로 사용
        popular_lessons = await db.User_Lesson_Progress.aggregate([
            {"$group": {"_id": "$lesson_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit}
        ]).to_list(length=limit)
        
        # 레슨 정보 추가
        popular_searches = []
        for lesson_stat in popular_lessons:
            lesson = await db.Lessons.find_one(
                {"_id": lesson_stat["_id"]},
                {"sign_text": 1, "content_type": 1}
            )
            if lesson:
                popular_searches.append({
                    "text": lesson.get("sign_text", ""),
                    "type": lesson.get("content_type", ""),
                    "search_count": lesson_stat["count"]
                })
        
        return APIResponse.success(data={
            "popular_searches": popular_searches,
            "total": len(popular_searches)
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get popular searches: {str(e)}")

@router.get("/lessons/recent")
async def get_recent_searches(
    limit: int = Query(default=10, ge=1, le=20, description="최근 검색어 수"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """최근 검색어 조회 (실제 구현 시 사용자별 검색 기록 필요)"""
    
    # 현재는 최근 추가된 레슨들을 반환
    try:
        recent_lessons = await db.Lessons.find(
            get_post_filter(),
            {
                "_id": 0,
                "sign_text": 1,
                "content_type": 1,
                "created_at": 1
            }
        ).sort("_id", -1).limit(limit).to_list(length=limit)
        
        recent_searches = [
            {
                "text": lesson.get("sign_text", ""),
                "type": lesson.get("content_type", ""),
                "added_at": lesson.get("created_at")
            }
            for lesson in recent_lessons
        ]
        
        return APIResponse.success(data={
            "recent_searches": recent_searches,
            "total": len(recent_searches)
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get recent searches: {str(e)}")

@router.get("/stats")
async def get_search_stats(
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """검색 통계 조회"""
    
    try:
        # 검색 가능한 레슨 수
        total_searchable = await db.Lessons.count_documents(get_post_filter())
        
        # 콘텐츠 타입별 분포
        content_type_stats = await db.Lessons.aggregate([
            {"$match": get_post_filter()},
            {"$group": {"_id": "$content_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]).to_list(length=None)
        
        content_distribution = [
            {"type": stat["_id"], "count": stat["count"]}
            for stat in content_type_stats
        ]
        
        stats = {
            "total_searchable_lessons": total_searchable,
            "content_type_distribution": content_distribution,
            "search_features": {
                "vector_search": True,
                "text_search": True,
                "auto_complete": True,
                "content_filtering": True
            }
        }
        
        return APIResponse.success(data=stats)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get search stats: {str(e)}")

# 하위 호환성을 위한 deprecated 엔드포인트
@router.get("")
async def semantic_search_deprecated(
    q: str = Query(..., min_length=1),
    k: int = 10,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """@deprecated Use /search/lessons instead"""
    
    try:
        # 기존 로직과 동일하게 유지
        COL = AsyncIOMotorClient(settings.MONGODB_URL)["waterandfish"]["Lessons"]
        
        q_vec = embed(q)
        
        pipe = [
            {
                "$vectorSearch": {
                    "index": "waterandfish_lessons",
                    "path": "embedding",
                    "queryVector": q_vec,
                    "limit": k,
                    "numCandidates": k * 5
                }
            },
            {"$match": get_post_filter()},
            {"$project": get_projection()}
        ]
        
        hits = await COL.aggregate(pipe).to_list(k)
        
        # fallback: prefix 검색
        if not hits:
            prefix_cond = {
                **get_post_filter(),
                "sign_text": {"$regex": f"^{q}"}
            }
            hits = await COL.find(
                prefix_cond,
                get_projection()
            ).limit(k).to_list(length=k)
        
        if not hits:
            raise HTTPException(status_code=404, detail="No results")
        
        return hits
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
