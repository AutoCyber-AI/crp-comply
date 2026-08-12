"""
CRP Gateway / Comply shared PostgreSQL schema.

Functions here create tables in whichever logical database is supplied.
They are idempotent (IF NOT EXISTS).
"""

from __future__ import annotations

import asyncpg

_GATEWAY_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_audit_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    session_id TEXT NOT NULL,
    window_id TEXT NOT NULL DEFAULT '',
    tenant_id TEXT,
    event_index INTEGER NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    event_hmac TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_session_index
    ON gateway_audit_events(session_id, event_index);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
    ON gateway_audit_events(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant
    ON gateway_audit_events(tenant_id);

CREATE TABLE IF NOT EXISTS gateway_audit_windows (
    id BIGSERIAL PRIMARY KEY,
    window_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    tenant_id TEXT,
    window_number INTEGER NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    response_content_hash TEXT NOT NULL,
    dpe_report_hash TEXT NOT NULL,
    window_hmac TEXT NOT NULL,
    previous_window_hmac TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_windows_session
    ON gateway_audit_windows(session_id, window_number);
"""


_GATEWAY_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_sessions (
    session_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    user_id TEXT,
    conversation_id TEXT,
    policy_id TEXT,
    strategy TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active',
    chain_tip_hmac TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_gateway_sessions_tenant
    ON gateway_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_gateway_sessions_user
    ON gateway_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_gateway_sessions_status
    ON gateway_sessions(status);

CREATE TABLE IF NOT EXISTS gateway_windows (
    window_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES gateway_sessions(session_id) ON DELETE CASCADE,
    window_number INTEGER NOT NULL,
    parent_window_id TEXT,
    continuation_count INTEGER NOT NULL DEFAULT 0,
    dag_node_id TEXT,
    quality_hash TEXT,
    dpe_report JSONB,
    dpe_report_hash TEXT,
    soft_budget_used INTEGER NOT NULL DEFAULT 0,
    hard_budget_used INTEGER NOT NULL DEFAULT 0,
    model_provider TEXT,
    model_name TEXT,
    latency_ms REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, window_number)
);

CREATE INDEX IF NOT EXISTS idx_gateway_windows_session
    ON gateway_windows(session_id, window_number);

CREATE TABLE IF NOT EXISTS gateway_documents (
    document_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    user_id TEXT,
    source_url TEXT,
    content_hash TEXT NOT NULL,
    content_type TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    chunks JSONB NOT NULL DEFAULT '[]',
    cdr_envelope JSONB,
    ckf_etag TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gateway_documents_tenant
    ON gateway_documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_gateway_documents_status
    ON gateway_documents(status);

CREATE TABLE IF NOT EXISTS gateway_pipelines (
    pipeline_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    user_id TEXT,
    session_id TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    config JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    result JSONB,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_gateway_pipelines_tenant
    ON gateway_pipelines(tenant_id);
CREATE INDEX IF NOT EXISTS idx_gateway_pipelines_session
    ON gateway_pipelines(session_id);
"""


async def ensure_gateway_schema(pool: asyncpg.Pool) -> None:
    """Create Gateway audit + state tables."""
    async with pool.acquire() as conn:
        await conn.execute(_GATEWAY_AUDIT_SCHEMA)
        await conn.execute(_GATEWAY_STATE_SCHEMA)
