"""CRP Learning Reranker — server-side feedback loop.

The **second half** of the SearXNG-host-side agent. The main API
(crp-comply-search) reports back which citations actually got used in
the final agent answer (the citation_id round-trip is already plumbed
through the audit trail). That signal is recorded into a small SQLite
on this sidecar's volume and turned into a per-(intent, engine)
exponentially-decayed utility score.

The router plugin reads ``engine_scores(intent)`` to bias future
fan-outs. Effect: engines that consistently produce useful citations
for a given intent climb the ordering; engines whose results never
get cited drift down — the host learns *for itself* which engines
matter for compliance work.

Endpoint: ``POST /crp/feedback`` (registered by SearXNG plugin hook).
Payload::

    {
      "intent": "regulation_text",
      "engine":  "eur_lex",
      "useful":  true,
      "weight":  1.0          # optional, defaults to 1.0
    }

Storage: ``settings.crp_agent.reranker.feedback_db``.
Decay: half-life from ``crp_agent.reranker.decay_half_life_days``.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import threading
import time
from typing import Any

from flask import jsonify, request

from searx import settings
from searx.plugins import Plugin, PluginInfo

logger = logging.getLogger("searx.plugins.crp_learning_reranker")

_LOCK = threading.Lock()
_DEFAULTS = {
    "feedback_db": "/var/lib/searxng-crp/feedback.sqlite",
    "decay_half_life_days": 14,
    "min_observations": 3,
}


def _cfg() -> dict[str, Any]:
    cfg = (settings.get("crp_agent") or {}).get("reranker") or {}
    out = dict(_DEFAULTS)
    out.update({k: cfg[k] for k in cfg if k in _DEFAULTS})
    return out


def _connect() -> sqlite3.Connection:
    cfg = _cfg()
    path = cfg["feedback_db"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
          intent TEXT NOT NULL,
          engine TEXT NOT NULL,
          useful INTEGER NOT NULL,
          weight REAL NOT NULL DEFAULT 1.0,
          ts     REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_ie ON feedback(intent, engine)")
    return conn


def record_feedback(intent: str, engine: str, useful: bool, weight: float = 1.0) -> None:
    intent = (intent or "general").lower()
    engine = (engine or "").lower()
    if not engine:
        return
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO feedback(intent, engine, useful, weight, ts) VALUES (?, ?, ?, ?, ?)",
                (intent, engine, 1 if useful else 0, float(weight), time.time()),
            )
        finally:
            conn.close()


def engine_scores(intent: str) -> dict[str, float]:
    """Return ``{engine: score}`` for the given intent, decayed to now."""
    intent = (intent or "general").lower()
    cfg = _cfg()
    half_life = float(cfg["decay_half_life_days"]) * 86400.0
    min_obs = int(cfg["min_observations"])
    if half_life <= 0:
        return {}
    lambda_ = math.log(2.0) / half_life
    now = time.time()

    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT engine, useful, weight, ts FROM feedback WHERE intent = ?",
                (intent,),
            )
            for engine, useful, weight, ts in cur:
                age = max(0.0, now - float(ts))
                decayed = float(weight) * math.exp(-lambda_ * age)
                signed = decayed if useful else -decayed * 0.25
                scores[engine] = scores.get(engine, 0.0) + signed
                counts[engine] = counts.get(engine, 0) + 1
        finally:
            conn.close()

    return {e: s for e, s in scores.items() if counts.get(e, 0) >= min_obs}


# ----------------------------------------------------------------------
# SearXNG plugin contract.
# ----------------------------------------------------------------------
class CrpLearningReranker(Plugin):
    id = "CRP Learning Reranker"

    def __init__(self, plg_cfg: Any | None = None):
        super().__init__(plg_cfg)
        self.info = PluginInfo(
            id=self.id,
            name="CRP Learning Reranker",
            description="Records citation-utility feedback and biases the router on intent.",
            preference_section="general",
        )


plugin = CrpLearningReranker()


def init(app, plg_settings) -> bool:  # noqa: D401
    """Register the /crp/feedback endpoint."""

    @app.route("/crp/feedback", methods=["POST"])  # type: ignore[misc]
    def _crp_feedback():  # pragma: no cover — exercised end-to-end on Railway
        if not request.is_json:
            return jsonify({"ok": False, "error": "json required"}), 400
        body = request.get_json(silent=True) or {}
        try:
            record_feedback(
                intent=str(body.get("intent") or "general"),
                engine=str(body.get("engine") or ""),
                useful=bool(body.get("useful")),
                weight=float(body.get("weight") or 1.0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("crp_feedback failed: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True})

    @app.route("/crp/scores/<intent>", methods=["GET"])  # type: ignore[misc]
    def _crp_scores(intent: str):  # pragma: no cover
        return jsonify({"intent": intent, "scores": engine_scores(intent)})

    return True
