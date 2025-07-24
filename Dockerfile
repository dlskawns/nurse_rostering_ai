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


# ───────── OS 패키지 & uv 설치 ─────────
RUN apt-get update && \
    apt-get install --no-install-recommends -y curl build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    # ▸ uv 설치(공식 스크립트)
    curl -LsSf https://astral.sh/uv/install.sh | sh && \ 
    ln -s /root/.local/bin/uv /usr/local/bin/uv && \
    uv venv && \
    uv sync
ENV PATH="/root/.local/bin:${PATH}"

# ───────── 애플리케이션 소스 복사 ─────────
COPY . /app

# ───────── 런타임 환경 변수 ─────────
ENV PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

# ───────── 헬스체크 (ALB 용) ─────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fs http://localhost:${PORT}/health/alb || exit 1

# ───────── 컨테이너 시작 CMD ─────────
CMD uvicorn app.main:app --host 0.0.0.0 --port 8000
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
