# Single image that builds the SPA and serves it from the API on :8000.
#
# Two stages because the frontend needs node and the runtime needs Python; the
# final image carries only the built assets.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

# ffmpeg is not optional: audio duration probing, whisper decoding and the video
# export all shell out to it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
# extras are needed: speech (fugashi + whisper) for alignment/cards, export for
# the video renderer. GPU is deliberately left out so the image stays portable.
# Not --frozen: the lock is regenerated when dependencies change.
RUN uv sync --no-dev --extra speech --extra export

COPY backend/ ./
COPY --from=web /web/dist /app/../frontend/dist

ENV DATA_DIR=/data \
    EXPORT_DIR=/exports \
    UTALEARN_BASE_URL=http://127.0.0.1:8000

RUN mkdir -p /data /exports
VOLUME ["/data", "/exports"]

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
