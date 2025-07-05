# API 리팩토링 문서

## 개요
기존의 `learning.py` 파일이 너무 크고 복잡하여 RESTful API 원칙에 따라 리소스별로 분리했습니다.

## 새로운 API 구조

### 1. 카테고리 API (`/categories`)
- **POST** `/categories` - 카테고리 생성
- **GET** `/categories` - 모든 카테고리 조회 (챕터와 레슨 포함)
- **GET** `/categories/{category_id}` - 특정 카테고리 조회
- **PUT** `/categories/{category_id}` - 카테고리 수정
- **DELETE** `/categories/{category_id}` - 카테고리 삭제

### 2. 챕터 API (`/chapters`)
- **POST** `/chapters` - 챕터 생성
- **GET** `/chapters` - 모든 챕터 조회
- **GET** `/chapters/{chapter_id}` - 특정 챕터 조회
- **PUT** `/chapters/{chapter_id}` - 챕터 수정
- **DELETE** `/chapters/{chapter_id}` - 챕터 삭제
- **POST** `/chapters/{chapter_id}/lessons/connect` - 챕터에 레슨 연결

### 3. 레슨 API (`/lessons`)
- **POST** `/lessons` - 레슨 생성
- **GET** `/lessons` - 모든 레슨 조회
- **GET** `/lessons/{lesson_id}` - 특정 레슨 조회
- **PUT** `/lessons/{lesson_id}` - 레슨 수정
- **DELETE** `/lessons/{lesson_id}` - 레슨 삭제

### 4. 프로그레스 API (`/progress`)
- **POST** `/progress/categories/{category_id}` - 카테고리 프로그레스 초기화
- **POST** `/progress/chapters/{chapter_id}` - 챕터 프로그레스 초기화
- **POST** `/progress/lessons/events` - 레슨 이벤트 업데이트
- **GET** `/progress/overview` - 전체 진도 개요 조회
- **GET** `/progress/recent-learning` - 최근 학습 조회
- **GET** `/progress/failures/{username}` - 사용자별 실패한 레슨 조회

### 5. 학습/퀴즈 API (`/study`)
- **POST** `/study/letters` - 글자 학습 시작
- **POST** `/study/letters/result` - 글자 퀴즈 결과 제출
- **POST** `/study/sessions` - 세션 학습 시작
- **POST** `/study/sessions/result` - 세션 퀴즈 결과 제출

### 6. 출석 API (`/attendance`)
- **GET** `/attendance/streak` - 출석 스트릭 조회
- **POST** `/attendance/complete` - 오늘 출석 완료

### 7. 사용자별 API (`/users`)
- **GET** `/users/{user_id}/progress` - 사용자의 전체 진도 조회
- **POST** `/users/{user_id}/progress/categories/{category_id}` - 사용자 카테고리 진도 초기화
- **POST** `/users/{user_id}/progress/chapters/{chapter_id}` - 사용자 챕터 진도 초기화
- **POST** `/users/{user_id}/progress/lessons/events` - 사용자 레슨 이벤트 업데이트
- **GET** `/users/{user_id}/progress/overview` - 사용자 진도 개요 조회
- **GET** `/users/{user_id}/recent-learning` - 사용자 최근 학습 조회
- **GET** `/users/{user_id}/attendance/streak` - 사용자 출석 스트릭 조회
- **POST** `/users/{user_id}/attendance/complete` - 사용자 오늘 출석 완료

## 주요 변경사항

### 1. 엔드포인트 네이밍 규칙 통일
- **명사형 사용**: 리소스 중심으로 `/categories`, `/chapters`, `/lessons` 등
- **동사형 피하기**: `/getCategories` → `/categories` (GET)
- **복수형 사용**: `/category` → `/categories`
- **하위 리소스 경로 표현**: `/categories/{category_id}/chapters`

### 2. HTTP 메서드 일관성
- **GET**: 데이터 조회
- **POST**: 데이터 생성
- **PUT**: 데이터 전체 수정
- **DELETE**: 데이터 삭제

### 3. 응답 포맷 통일
모든 API 응답이 다음 구조를 따릅니다:
```json
{
  "success": true,
  "data": {...},
  "message": "성공 메시지"
}
```

### 4. 에러 처리 통일
모든 API에서 일관된 에러 응답:
```json
{
  "detail": "에러 메시지"
}
```

## 마이그레이션 가이드

### 기존 엔드포인트 → 새로운 엔드포인트

| 기존                                    | 새로운 |
|----------------------------------------|------------------------------------------------|
| `POST /learning/category`              | `POST /categories`                             |
| `GET /learning/categories`             | `GET  /categories`                             |
| `GET /learning/chapter/{category}`     | `GET  /categories/{category_id}`               |
| `POST /learning/chapter`               | `POST /chapters`                               |
| `GET /learning/chapter/all`            | `GET  /chapters`                               |
| `POST /learning/lesson`                | `POST /lessons`                                |
| `GET /learning/lesson/all`             | `GET  /lessons`                                |
| `POST /learning/connect/lesson`        | `POST /chapters/{chapter_id}/lessons/connect`  |
| `POST /learning/progress/category/set` | `POST /progress/categories/{category_id}`      |
| `POST /learning/progress/chapter/set`  | `POST /progress/chapters/{chapter_id}`         |
| `POST /learning/study/letter`          | `POST /study/letters`                          |
| `POST /learning/result/letter`         | `POST /study/letters/result`                   |
| `POST /learning/study/session`         | `POST /study/sessions`                         |
| `POST /learning/result/session`        | `POST /study/sessions/result`                  |
| `GET /learning/recent-learning`        | `GET  /progress/recent-learning`               |
| `GET /learning/progress/overview`      | `GET  /progress/overview`                      |
| `GET /user/daily-activity/streak`      | `GET  /attendance/streak`                      |
| `POST /user/daily-activity/complete`   | `POST /attendance/complete`                    |

## 공통 유틸리티

### `utils.py`
- `convert_objectid()`: ObjectId를 문자열로 변환
- `get_user_id_from_token()`: 토큰에서 user_id 추출
- `require_auth()`: 인증이 필요한 엔드포인트용
- `validate_object_id()`: ObjectId 유효성 검사
- `create_success_response()`: 성공 응답 생성
- `create_error_response()`: 에러 응답 생성

## 하위 호환성
기존 `/learning` 엔드포인트는 deprecated 처리되었지만, 하위 호환성을 위해 유지됩니다. 새로운 API 사용을 권장합니다. 