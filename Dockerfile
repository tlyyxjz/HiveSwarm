# HiveSwarm production image
FROM python:3.13-slim AS base

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python deps first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    pydantic>=2.5 \
    litellm>=1.30 \
    fastapi>=0.110 \
    'uvicorn[standard]>=0.27' \
    'tomli>=2.0; python_version < "3.11"' \
    httpx>=0.27 \
    gradio>=4.15

# Source
COPY core/ ./core/
COPY layers/ ./layers/
COPY stub/ ./stub/
COPY src/ ./src/
COPY gateway/ ./gateway/
COPY sdk/ ./sdk/
COPY skills/ ./skills/
COPY config/ ./config/

# Runtime data dir
RUN mkdir -p /app/runtime/logs /app/runtime/data
ENV HIVESWARM_RUNTIME_DIR=/app/runtime

# Default: gateway
EXPOSE 8000 7860

CMD ["python", "-m", "gateway"]