# crp-comply-searxng — opinionated, audit-grade SearXNG sidecar.
#
# Strategy: take the upstream image as a clean base, then overlay our
# settings.yml, limiter.toml, custom engines, and intelligent plugins.
# The submodule at ./searxng/ exists for any fork-level source patches
# we ever need (none right now); the runtime image does NOT build from
# it — we pin the upstream tag so reproducible audits are trivial.

FROM searxng/searxng:2026.5.2-aefc3c316 AS base

ENV INSTANCE_NAME="crp-comply-searxng" \
    AUTOCOMPLETE="duckduckgo" \
    BASE_URL="" \
    SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml

# Overlay configs.
COPY settings.yml      /etc/searxng/settings.yml
COPY limiter.toml      /etc/searxng/limiter.toml

# Custom engines — copied FLAT into the engines directory.
# SearXNG 2026.x loads engines as flat .py files; subdirectory packages
# are not supported. The engine: field in settings.yml must match the
# filename without .py (e.g. engine: crp_eur_lex → crp_eur_lex.py).
COPY engines/eur_lex.py  /usr/local/searxng/searx/engines/crp_eur_lex.py
COPY engines/edpb.py     /usr/local/searxng/searx/engines/crp_edpb.py
COPY engines/bailii.py   /usr/local/searxng/searx/engines/crp_bailii.py
COPY engines/curia.py    /usr/local/searxng/searx/engines/crp_curia.py

# Server-side intelligent agent plugins (engine routing + feedback learner).
COPY plugins/          /usr/local/searxng/searx/plugins/_crp/

# Make the plugins importable as searx.plugins._crp.*
RUN mkdir -p /var/lib/searxng-crp \
 && touch /usr/local/searxng/searx/plugins/_crp/__init__.py

# NOTE: persistent storage for the learning-reranker SQLite is provided
# by a Railway-managed Volume mounted at /var/lib/searxng-crp. We do NOT
# declare a Dockerfile VOLUME because Railway forbids it (use Railway
# Volumes in the service settings instead).

# Health endpoint is served by SearXNG itself at /healthz.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
