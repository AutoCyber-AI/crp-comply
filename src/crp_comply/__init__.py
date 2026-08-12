# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply — AI Governance & EU AI Act Compliance Platform."""

__version__ = "0.2.0"

# Side-effect imports: register the UIE Stage 4 shim and install
# warning filters for known-harmless upstream noise (gliner truncation,
# huggingface_hub resume_download, transformers sentencepiece). Must
# happen before any code path constructs ``crp.extraction.ExtractionPipeline``.
from crp_comply import extraction as _extraction  # noqa: F401

from crp_comply.core import CRPComply, DPIAReport, SessionAuditReport

__all__ = ["CRPComply", "DPIAReport", "SessionAuditReport"]
