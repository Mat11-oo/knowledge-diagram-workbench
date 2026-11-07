# syntax=docker/dockerfile:1
FROM python:3.12-slim

# ffmpeg: clip concatenation and audio/video post-processing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    SFA_HOST=0.0.0.0

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# HTML template pipelines render through Chromium; enable with --build-arg INSTALL_PLAYWRIGHT=1.
ARG INSTALL_PLAYWRIGHT=0
RUN if [ "$INSTALL_PLAYWRIGHT" = "1" ]; then uv run playwright install --with-deps chromium; fi

COPY . .

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "python", "api_server.py"]
