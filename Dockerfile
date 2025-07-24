# ───────── 0. Base image ─────────
FROM python:3.12-slim

# 패키지 설치에 필요한 메타만 남겨서 이미지 크기 ↓
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# ───────── 1. 시스템 패키지 + uv 설치 ─────────
RUN apt-get update && \
    apt-get install --no-install-recommends -y curl build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    # ▸ uv 설치
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -s /root/.local/bin/uv /usr/local/bin/uv

ENV PATH="/root/.local/bin:${PATH}"

# ───────── 2. Python deps layer ─────────
#   · 의존성 파일 먼저 복사 → 캐시 효율 ↑
COPY pyproject.toml requirements.txt* ./

RUN uv pip install --system --no-cache-dir --upgrade-strategy eager || \
    uv pip install --system --no-cache-dir

# ───────── 3. 애플리케이션 코드 ─────────
COPY app ./app
COPY main.py .

# ───────── 4. 런타임 ─────────
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fs http://localhost:8000/health/alb || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
