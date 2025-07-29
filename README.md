<img width="752" height="1061" alt="스크린샷 2025-07-29 오후 9 51 25" src="https://github.com/user-attachments/assets/c4ef648a-1270-47c8-95de-9d622a72ff3b" />

 수어지교 (Team5 Water and Fish)

손끝에서 시작되는 인연 - 수어 학습 및 커뮤니티 플랫폼

---

## 📝 프로젝트 소개

**수어지교**는 수어(한국어 수화) 학습과 커뮤니티를 위한 올인원 플랫폼입니다. 
- **목표**: 누구나 쉽고 재미있게 수어를 배우고, 실생활에 활용할 수 있도록 지원
- **주요 특징**:
  - 체계적인 카테고리/챕터/레슨 기반 학습
  - 퀴즈, 진도, 출석, 뱃지 등 동기부여 요소
  - 소셜 로그인, 추천, ML 기반 수어 인식 등 최신 기술 적용
  - WebM 동영상 스트리밍 지원
- **대상**: 수어를 처음 배우는 일반인, 교육자, 청각장애인 등

---

## 📁 폴더/파일 구조

```
team5-waterandfish-BE/
├── src/
│   ├── api/           # API 라우터 (auth, chapters, lessons, animation, quiz, test 등)
│   ├── core/          # 설정, 인증, 환경변수 관리
│   ├── db/            # MongoDB 연결, 세션 관리
│   ├── models/        # Pydantic 모델
│   ├── services/      # 비즈니스 로직, ML, S3, WebSocket, 추천 등
│   └── main.py        # FastAPI 앱 진입점
├── scripts/           # 배포/운영/모니터링/유틸 스크립트
├── config/            # WebSocket 서버 등 설정 파일
├── tests/             # pytest 기반 API/유닛 테스트
├── pyproject.toml     # Python 의존성/설정
├── README.md          # 프로젝트 설명
└── ...
```

- **api/**: 각 도메인별 FastAPI 라우터 (RESTful)
  - animation.py: 수어 애니메이션 WebM 스트리밍
  - attendance.py: 출석 체크 관리
  - auth.py: 인증/인가 처리
  - badge.py: 사용자 뱃지 시스템
  - chapters.py: 학습 챕터 관리
  - lessons.py: 개별 레슨 관리
  - ml.py: 머신러닝 서비스 연동
  - quiz.py: 퀴즈 시스템
  - search.py: 검색 기능
  - test.py: 테스트 시스템
  - video_upload.py: 동영상 업로드 처리
- **services/**: DB/ML/외부 서비스 연동, 비즈니스 로직
  - sign_classifier_websocket_server.py: 수어 인식 WebSocket 서버
  - embedding.py: 텍스트 임베딩 서비스
  - ml_service.py: ML 모델 관리 서비스
  - model_server_manager.py: 수어 인식 WebSocket 서버 실행
  - s3_utils.py: AWS S3 연동 유틸리티
- **scripts/**: 서버 관리, 배포, 모니터링, 데이터 백필 등 자동화 스크립트
- **config/**: WebSocket 서버 등 환경설정 JSON/템플릿

---

## ⚡️ 설치 및 실행

### 1. 로컬 개발 환경

1. Python 3.9+ 설치
2. Poetry 설치 ([공식문서](https://python-poetry.org/docs/))
3. 의존성 설치
   ```bash
   poetry install
   ```
4. 환경 변수 설정 (.env 파일)
   ```env
   MONGODB_URL=mongodb://localhost:27017
   JWT_SECRET_KEY=your-secret-key
   GOOGLE_CLIENT_ID=your-google-client-id
   GOOGLE_CLIENT_SECRET=your-google-client-secret
   KAKAO_CLIENT_ID=your-kakao-client-id
   KAKAO_CLIENT_SECRET=your-kakao-client-secret
   AWS_ACCESS_KEY_ID=your-aws-access-key
   AWS_SECRET_ACCESS_KEY=your-aws-secret-key
   AWS_REGION=ap-northeast-2
   ```
5. 서버 실행
   ```bash
   poetry run uvicorn src.main:app --reload
   ```

### 2. Docker 환경 (권장)

```bash
# 빌드 및 실행
./build.sh
# 또는
# docker build -t team5-waterandfish-be:latest .
# docker run -p 8000:8000 team5-waterandfish-be:latest
```

### 3. 데이터베이스 준비
- MongoDB 인스턴스가 필요합니다. (로컬/클라우드 모두 가능)
- 초기 데이터/임베딩 백필: `src/scripts/backfill_embeddings.py` 등 활용

### 4. Conda 환경 사용 (선택사항)
프로젝트 루트에 `.conda` 디렉토리가 있는 경우:
```bash
# 직접 Python 인터프리터 실행
.conda/bin/python

# 또는 pip로 필요한 패키지 설치
.conda/bin/pip install -r requirements.txt
```

---

## 🔗 주요 API 엔드포인트 (요약)

| 경로 | 메서드 | 설명 | 인증 |
|------|--------|------|------|
| /auth/signin | POST | 로그인 | ❌ |
| /auth/signup | POST | 회원가입 | ❌ |
| /auth/delete-account | DELETE | 회원 탈퇴(이메일 검증) | ⭕ |
| /auth/google | GET | Google OAuth 시작 | ❌ |
| /auth/kakao | GET | Kakao OAuth 시작 | ❌ |
| /auth/{provider}/callback | POST | OAuth 콜백 처리 | ❌ |
| /anim/{lesson_id} | GET | 레슨 애니메이션 조회 (WebM) | ❌ |
| /chapters/{chapter_id} | GET | 챕터 학습 세션 조회 | ⭕ |
| /chapters/{chapter_id}/guide | GET | 챕터 학습 가이드 조회 | ❌ |
| /quiz/chapter/{chapter_id} | GET | 챕터 퀴즈 조회 | ⭕ |
| /quiz/chapter/{chapter_id}/submit | POST | 퀴즈 결과 제출 | ⭕ |
| /test | GET | 테스트 페이지 조회 | ❌ |
| /test/letter/{set_type}/{q_or_s} | GET | 글자 테스트 조회 | ⭕ |
| /test/letter/{set_type}/submit | POST | 글자 테스트 결과 제출 | ⭕ |
| /badge/check-badges | POST | 뱃지 획득 조건 확인 | ⭕ |
| /video_upload | POST | 동영상 업로드 | ❌ |
| ... | ... | ... | ... |

- ⭕: 인증 필요, ❌: 비로그인 접근 가능
- `/progress`, `/study`, `/attendance`, `/users` 등 RESTful 엔드포인트 다수 존재

### 공통 응답 예시
```json
{
  "success": true,
  "data": { ... },
  "message": "성공 메시지"
}
```

### 샘플 요청 (curl)
```bash
# 로그인
curl -X POST http://localhost:8000/auth/signin -H "Content-Type: application/json" -d '{"email":"test@test.com","password":"1234"}'

# 애니메이션 조회 (WebM)
curl -o animation.webm http://localhost:8000/anim/60f1a5b3e4b0a1b2c3d4e5f6
```

---

## 🎯 주요 기능 상세

- **사용자 인증**: 이메일/비밀번호, Google/Kakao 소셜 로그인, JWT 토큰 기반 인증/인가
- **챕터/레슨**: 계층적 수어 학습 구조, MongoDB 기반 데이터 관리
- **학습/퀴즈/진도**: 단어/챕터별 학습, 퀴즈, 진도/진행률 관리
- **출석/뱃지/동기부여**: 출석 체크, 뱃지 시스템, streak, 통계 등
- **ML 연동**: ML 모델(WebSocket) 연동, 실시간 수어 인식
- **애니메이션 스트리밍**: WebM 형식 수어 애니메이션 스트리밍 제공
- **운영/모니터링**: WebSocket 서버 관리, 배포/모니터링 스크립트, 서비스 헬스체크
- **테스트**: pytest 기반 단위/통합 테스트, 테스트용 DB 세팅 지원

---

## 🛠️ 기술 스택 및 아키텍처

### 백엔드
- **FastAPI**: 비동기 REST API 서버
- **MongoDB (Motor)**: NoSQL 데이터베이스, 비동기 드라이버
- **PyJWT**: JWT 인증/인가
- **Pydantic v2**: 데이터 검증/직렬화
- **Poetry**: 패키지/의존성 관리
- **WebSocket**: ML/실시간 서비스 연동
- **TensorFlow/Keras**: 수어 인식 모델
- **AWS S3**: 미디어 파일 저장소

### 프론트엔드 (별도 저장소)
- **React 18, Vite, TypeScript, React Router v6, Axios, Tailwind CSS**

### 기타
- **Docker**: 컨테이너 배포
- **Shell/Python Scripts**: 운영 자동화
- **WebM**: 동영상 스트리밍 포맷

### 아키텍처 개요
- FastAPI(REST) ↔ MongoDB
- FastAPI → WebSocket ML 서버
- FastAPI ↔ S3 등 외부 서비스
- 프론트엔드(React) ↔ FastAPI
- 클라이언트 ↔ WebM 스트리밍
- 클라이언트 ↔ 수어 인식 websocket 서버

---

## 🧪 테스트/운영/배포

- **테스트**: `pytest`로 실행, `tests/` 폴더 참고
- **운영/모니터링**: `scripts/` 내 `monitor_websocket_services.sh`, `check_websocket_servers.sh` 등 활용
- **배포**: `build.sh`, Dockerfile, config/websocket_servers.json 등 참고
- **DB 초기화/백필**: `src/scripts/backfill_embeddings.py`, `seed_embeddings.py` 등
- **성능 최적화**: 랜드마크 시퀸스로 수어인식 처리

---

## 🤝 기여/문의

- **기여 방법**: PR/이슈 등록, 코드 컨벤션(Python: black, isort 등) 준수
- **문의/이슈**: GitHub Issues 활용, 또는 팀원에게 직접 문의
- **참고 문서**: `API_REFACTOR.md`, `FRONTEND_ROUTE_API_MAPPING.md`, `WEBSOCKET_SERVICES_GUIDE.md` 등

---

수어지교와 함께 모두가 소통하는 세상을 만들어가요! 🙌
