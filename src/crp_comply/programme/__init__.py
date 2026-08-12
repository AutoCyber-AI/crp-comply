# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Programme tracker — obligation-lifecycle states.

Every obligation a tenant must satisfy (recipe-id × system) is modelled
as an :class:`ObligationLifecycle` record so the UI can show *exactly*
where the user is in the regulatory programme rather than treating each
deliverable as a one-shot file. See ``COMPLIANCE_MODEL_GAPS.md`` Gap #5.
"""

from .lifecycle import (
    InvalidTransition,
    LifecycleState,
    ObligationLifecycle,
    ProgrammeStore,
    get_programme_store,
    init_programme_store,
)

__all__ = [
    "InvalidTransition",
    "LifecycleState",
    "ObligationLifecycle",
    "ProgrammeStore",
    "init_programme_store",
    "get_programme_store",
]
