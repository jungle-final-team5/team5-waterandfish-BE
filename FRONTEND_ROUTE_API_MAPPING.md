# 프론트엔드 라우트와 백엔드 API 매핑

## 개요
프론트엔드 라우트 구조를 기준으로 백엔드 API를 개선하여 일관성과 직관성을 높였습니다.

## 매핑 테이블

### 1. 카테고리 관련
| 프론트엔드 라우트 | 백엔드 API | 설명 |
|------------------|------------|------|
| `/category` | `GET /category` | 모든 카테고리 조회 |
| `/category/:categoryId/chapters` | `GET /category/{category_id}/chapters` | 특정 카테고리의 챕터들 조회 |

### 2. 학습 관련
| 프론트엔드 라우트 | 백엔드 API | 설명 |
|------------------|------------|------|
| `/learn/word/:wordId` | `GET /learn/word/{word_id}` | 특정 단어 레슨 조회 |
| `/learn/chapter/:chapterId` | `GET /learn/chapter/{chapter_id}` | 챕터 학습 세션 조회 |
| `/learn/chapter/:chapterId/guide` | `GET /learn/chapter/{chapter_id}/guide` | 챕터 학습 가이드 조회 |
| - | `POST /learn/chapter/{chapter_id}/progress` | 학습 진행 상태 업데이트 |

### 3. 퀴즈 관련
| 프론트엔드 라우트 | 백엔드 API | 설명 |
|------------------|------------|------|
| `/quiz/chapter/:chapterId` | `GET /quiz/chapter/{chapter_id}` | 챕터 퀴즈 조회 |
| `/quiz/chapter/:chapterId/review` | `GET /quiz/chapter/{chapter_id}/review` | 챕터 퀴즈 리뷰 조회 |
| - | `POST /quiz/chapter/{chapter_id}/submit` | 퀴즈 결과 제출 |

### 4. 테스트 관련
| 프론트엔드 라우트 | 백엔드 API | 설명 |
|------------------|------------|------|
| `/test` | `GET /test` | 테스트 페이지 조회 |
| `/test/letter/:setType/:qOrs` | `GET /test/letter/{set_type}/{q_or_s}` | 글자 테스트 조회 |
| - | `POST /test/letter/{set_type}/submit` | 글자 테스트 결과 제출 |

### 5. 리뷰 관련
| 프론트엔드 라우트 | 백엔드 API | 설명 |
|------------------|------------|------|
| `/review` | `GET /review` | 리뷰 페이지 조회 |
| - | `POST /review/mark-reviewed` | 리뷰 완료 표시 |
| - | `GET /review/stats` | 리뷰 통계 조회 |

## 주요 개선사항

### 1. URL 구조 일치
- 프론트엔드 라우트와 백엔드 API 경로가 일치하도록 개선
- 복수형에서 단수형으로 변경 (`/categories` → `/category`)
- 중첩 구조 유지 (`/category/:categoryId/chapters`)

### 2. 기능별 API 분리
- **학습**: `/learn` - 단어 학습, 챕터 학습, 가이드
- **퀴즈**: `/quiz` - 퀴즈 조회, 리뷰, 결과 제출
- **테스트**: `/test` - 글자 테스트, 결과 제출
- **리뷰**: `/review` - 리뷰 페이지, 통계

### 3. 일관된 응답 형식
```json
{
  "success": true,
  "data": { ... },
  "message": "성공 메시지"
}
```

### 4. 인증 처리
- 선택적 인증: 일부 API는 비로그인 사용자도 접근 가능
- 필수 인증: 진행 상태 업데이트, 결과 제출 등은 로그인 필요

## 사용 예시

### 카테고리 조회
```bash
curl http://localhost:8000/category
```

### 챕터 학습
```bash
curl http://localhost:8000/learn/chapter/507f1f77bcf86cd799439011
```

### 퀴즈 조회
```bash
curl http://localhost:8000/quiz/chapter/507f1f77bcf86cd799439011
```

### 글자 테스트
```bash
curl http://localhost:8000/test/letter/consonant/s
```

### 리뷰 페이지
```bash
curl http://localhost:8000/review
```

## 하위 호환성
기존 RESTful API 구조도 유지하여 하위 호환성을 보장합니다:
- `/categories` (기존)
- `/chapters` (기존)
- `/lessons` (기존)
- `/progress` (기존)
- `/study` (기존)
- `/attendance` (기존)
- `/users` (기존)

## 장점
1. **직관성**: 프론트엔드 라우트와 백엔드 API가 일치
2. **일관성**: URL 구조와 응답 형식이 통일
3. **확장성**: 기능별로 분리되어 유지보수 용이
4. **호환성**: 기존 API도 유지하여 안전한 마이그레이션 가능 