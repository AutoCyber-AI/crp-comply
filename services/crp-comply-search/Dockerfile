# syntax=docker/dockerfile:1.6
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build deps for any wheels with C extensions, then drop them.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --upgrade pip \
 && pip install .

# Run as non-root.
RUN useradd --create-home --uid 10001 sidecar
USER sidecar

EXPOSE 8081
ENV PORT=8081

# uvicorn directly so we get fast shutdown signals.
CMD ["sh", "-c", "exec python -m crp_comply_search"]
