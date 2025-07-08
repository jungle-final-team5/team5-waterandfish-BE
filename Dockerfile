# syntax=docker/dockerfile:1

#######################
# 1️⃣ Builder stage
#######################
FROM python:3.11-slim AS builder

# 빌드 도구만 임시 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- 1. Poetry → requirements.txt로 변환 ---
ENV POETRY_VERSION=1.8.2
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock* ./
RUN poetry export --without-hashes --only main -f requirements.txt -o requirements.txt

# --- 2. venv + wheel 캐싱 ---
ENV VENV_PATH=/opt/venv
RUN python -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# BuildKit 캐시 활용 → 재빌드 10배↑ 빠름
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# (선택) 앱 코드까지 미리 복사해 테스트·Mypy 등 실행 가능
COPY src/ src/

#######################
# 2️⃣ Runtime stage
#######################
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 && rm -rf /var/lib/apt/lists/* && \
    apt-get install libglib2.0-0 -y

# venv 통째로 복사 (시스템 툴·Poetry는 제외)
ENV VENV_PATH=/opt/venv
ENV PATH="$VENV_PATH/bin:$PATH"
COPY --from=builder $VENV_PATH $VENV_PATH

# 실제 어플리케이션 소스만 복사
COPY src/ src/

ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
