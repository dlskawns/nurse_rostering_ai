# ───────── 베이스 이미지 ─────────
# Python 3.13 slim (공식) ─ ARM/AMD 모두 OK
FROM python:3.12

# 작업 디렉토리 설정
WORKDIR /app

# 소스 코드 복사
COPY app ./app
COPY requirements.txt .
COPY pyproject.toml .


# ───────── 빌드 인자 (워크플로우에서 주입) ─────────
ARG ENV=dev
ARG GOOGLE_API_KEY
ARG ANTHROPIC_API_KEY
ARG OPENAI_API_KEY
# 환경 변수 설정 진행
ENV ENV=${ENV}
ENV GOOGLE_API_KEY=${GOOGLE_API_KEY}
ENV ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# ───────── OS 패키지 최소 설치 ─────────
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        build-essential curl && \
    rm -rf /var/lib/apt/lists/*


COPY requirements.txt* pyproject.toml* uv.lock* poetry.lock* ./


# 2) uv 설치 후 의존성 설치  (※  --require‑hashes 제거)
RUN pip install --no-cache-dir -U pip uv && \
    uv pip install --system --no-cache-dir --upgrade-strategy eager || \
    uv pip install --system --no-cache-dir
# ───────── 애플리케이션 소스 복사 ─────────
COPY . /app

# ───────── 런타임 환경 변수 ─────────
ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    APP_ENV=${APP_ENV} \
    OPENAI_API_KEY=${OPENAI_API_KEY} \
    PERPLEXITY_API_KEY=${PERPLEXITY_API_KEY} \
    ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}

EXPOSE 8000

# ───────── 헬스체크 (ALB 용) ─────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fs http://localhost:${PORT}/health/alb || exit 1

# ───────── 컨테이너 시작 CMD ─────────
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
