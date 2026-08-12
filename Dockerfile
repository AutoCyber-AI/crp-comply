# ── Stage 1: Build React Frontend ──────────────────────────────
FROM node:26-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit
COPY frontend/ ./
# VITE_CLERK_PUBLISHABLE_KEY is a public, publishable frontend key (safe to
# embed in the bundle). Railway does not support --mount=type=secret, so we
# pass it via ARG/ENV at build time.
ARG VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY
RUN npm run build

# ── Stage 2: Python Backend ───────────────────────────────────
FROM python:3.13-slim AS runtime

LABEL maintainer="Constantinos Vidiniotis <contact@crprotocol.io>"
LABEL description="CRP Comply — AI Governance & EU AI Act Compliance Platform"
LABEL vendor="AutoCyber AI Pty Ltd"

# Security: create non-root user + install gosu for privilege dropping.
# Also install C++ build tools needed to compile hnswlib (pulled in by
# crprotocol[full]) and other native extensions.  The build-dep layer is
# kept as a separate RUN so it can be dropped after the pip install stage.
RUN groupadd -r comply && useradd -r -g comply -m comply && \
    apt-get update && apt-get install -y --no-install-recommends \
        gosu \
        build-essential \
        g++ \
        cmake \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml README.md ./
COPY src/ src/
COPY crp_shared/ crp_shared/
# NOTE: corpus/_scraped/ is gitignored (regenerated per deploy via the
# auto-ingest step in the FastAPI lifespan). On first boot, if the
# directory is missing the lifespan runs the scrapers + builds the
# index automatically. We deliberately do NOT COPY corpus here so the
# image stays slim and the deploy always pulls the latest regulation
# text on first boot. To pre-bake the corpus at build time, set
# CRP_COMPLY_BAKE_CORPUS=true in the build args and uncomment the
# COPY directive below.
# COPY corpus/_scraped/ corpus/_scraped/
# Install Python dependencies. We install the `.[agent,rag,pdf,ml]` extras
# so that the deployed image ships with full agent + retrieval-augmented
# generation + PDF rendering + ML extraction (GLiNER NER) support
# (sentence-transformers, pdfplumber, weasyprint, gliner). This adds
# ~1.5GB to the image but is required for the production feature set —
# running without these extras silently degrades the /agent and /reports
# endpoints, and the CRP extraction pipeline logs "GLiNER not available
# — Stage 3 will be skipped".
# hnswlib (crprotocol[full]) builds a C++ extension — build-essential /
# g++ / cmake must be present at this step.
RUN pip install --no-cache-dir ".[agent,rag,pdf,ml]" && \
    pip install --no-cache-dir uvicorn[standard] && \
    apt-get purge -y --auto-remove build-essential g++ cmake pkg-config && \
    rm -rf /var/lib/apt/lists/*

# Pre-warm GLiNER weights into the image so the first /agent call doesn't
# block on a 200MB Hugging Face download. Failures are tolerated (e.g.
# offline build environments) — the runtime fall-through still works.
# Note: TRANSFORMERS_CACHE is deprecated in transformers v5; HF_HOME is
# the canonical knob and is honoured by transformers, sentence-transformers,
# and huggingface_hub.
ENV HF_HOME=/app/.hf_cache \
    SENTENCE_TRANSFORMERS_HOME=/app/.hf_cache
RUN mkdir -p /app/.hf_cache && \
    python -c "from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_base')" \
        || echo "[build] GLiNER pre-warm skipped (offline build); model will be fetched at runtime."

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Create data directory for auth persistence (chown happens at runtime via entrypoint)
RUN mkdir -p /app/data && chown -R comply:comply /app/.hf_cache

# Entrypoint: fixes volume ownership at startup, then drops to comply user
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Environment
ENV CRP_COMPLY_HOST=0.0.0.0
ENV CRP_COMPLY_PORT=8400
ENV CRP_COMPLY_DATA_DIR=/app/data
ENV CRP_COMPLY_FRONTEND_DIR=/app/frontend/dist

EXPOSE 8400

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT','8400') + '/api/v1/health')" || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
