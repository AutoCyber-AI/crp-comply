# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""OpenAI-compatible request/response schemas and audit record models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── OpenAI Chat Completion Request ─────────────────────────────


class ChatMessage(BaseModel):
    """A single message in a chat conversation."""

    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[Any] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request body."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    n: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    user: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    seed: int | None = None


# ── OpenAI Chat Completion Response ────────────────────────────


class ChoiceMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str = "assistant"
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class Choice(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: int = 0
    message: ChoiceMessage = Field(default_factory=ChoiceMessage)
    finish_reason: str | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[Choice] = Field(default_factory=list)
    usage: Usage | None = None
    system_fingerprint: str | None = None


# ── Audit Record ──────────────────────────────────────────────


class AuditRecord(BaseModel):
    """Tamper-evident compliance audit record for a proxied LLM request."""

    record_id: str
    timestamp: str
    model: str
    request_hash: str
    response_hash: str
    input_tokens: int = 0
    output_tokens: int = 0
    pii_detected_input: bool = False
    pii_detected_output: bool = False
    pii_categories: list[str] = Field(default_factory=list)
    injection_risk: str = "NONE"
    risk_level: str = "MINIMAL"
    data_classification: str = "INTERNAL"
    tier: str = "free"
    user_id: str = "anonymous"
    provenance: dict[str, Any] = Field(default_factory=dict)
    quality_tier: str = ""
    consent_purposes: list[str] = Field(default_factory=list)
    compliance_status: dict[str, bool] = Field(default_factory=dict)
    hmac_signature: str = ""


# ── Compliance Stats ──────────────────────────────────────────


class ComplianceStats(BaseModel):
    """Aggregate compliance statistics across all proxied requests."""

    total_requests: int = 0
    pii_detections: int = 0
    injection_attempts: int = 0
    compliance_rate: float = 100.0
    models_used: dict[str, int] = Field(default_factory=dict)
    risk_distribution: dict[str, int] = Field(default_factory=dict)
    quality_distribution: dict[str, int] = Field(default_factory=dict)
    consent_coverage: float = 0.0
    retention_tracked: int = 0
    lineage_tracked: int = 0
