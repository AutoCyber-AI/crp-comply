"""LLM-powered compliance agent package.

See ``LLM_INTELLIGENCE_DESIGN.md`` at the repo root for the full architecture.

* ``scrapers``/``ingest``/``corpus``/``rag`` — Phase 4.1 regulation corpus.
* ``llm`` — Phase 4.2 LLM adapter (:class:`ComplianceLLM`).
* ``tools`` — Phase 4.2 tool registry + four core tools.
* ``orchestrator`` — Phase 4.2 agent loop (:class:`ComplianceAgent`).
* ``rag_service`` — string-query facade over the corpus index.
"""

from __future__ import annotations

from .llm import ChatProvider, ChatTurn, ComplianceLLM
from .orchestrator import AgentResult, AgentState, ComplianceAgent, SYSTEM_PROMPT
from .rag_service import RagService
from .tools import (
    ClarificationNeeded,
    Tool,
    ToolRegistry,
    ToolResult,
    build_check_dpia_required_tool,
    build_check_dpo_required_tool,
    build_check_high_risk_criteria_tool,
    build_classify_ai_act_risk_tool,
    build_estimate_fine_exposure_tool,
    build_lookup_annex_tool,
    build_lookup_gdpr_tool,
    build_query_regulation_tool,
    build_recall_facts_tool,
    build_request_clarification_tool,
    build_run_injection_check_tool,
    build_run_pii_scan_tool,
    build_search_iso42001_tool,
    default_registry,
)

__all__ = [
    "scrapers",
    "ingest",
    "corpus",
    "rag",
    "ComplianceLLM",
    "ChatProvider",
    "ChatTurn",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "ClarificationNeeded",
    "default_registry",
    "build_query_regulation_tool",
    "build_classify_ai_act_risk_tool",
    "build_recall_facts_tool",
    "build_request_clarification_tool",
    "build_check_high_risk_criteria_tool",
    "build_lookup_annex_tool",
    "build_lookup_gdpr_tool",
    "build_search_iso42001_tool",
    "build_check_dpia_required_tool",
    "build_check_dpo_required_tool",
    "build_estimate_fine_exposure_tool",
    "build_run_pii_scan_tool",
    "build_run_injection_check_tool",
    "ComplianceAgent",
    "AgentResult",
    "AgentState",
    "SYSTEM_PROMPT",
    "RagService",
]
