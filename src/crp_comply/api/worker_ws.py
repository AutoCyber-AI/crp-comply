"""WebSocket endpoint for the SDK local-LLM worker.

Path: ``ws[s]://…/api/v1/agent/worker``

The SDK authenticates via ``Authorization: Bearer crp_…`` header ONLY.
The legacy ``?api_key=…`` query parameter was removed — it ended up in
reverse-proxy access logs (Railway, Cloudflare, nginx) and was the
source of a key-leakage incident reported in production.

Companion module: :mod:`crp_comply.api.worker_registry`.

Wire-protocol (server ↔ worker, JSON frames):

  Server → Worker:
    {"type":"request","request_id":"<uuid>","v":1,
     "payload":{"endpoint":"/v1/chat/completions",
                "model":"<str>",
                "messages":[…],"tools":[…],"max_tokens":int}}

  Worker → Server:
    {"type":"response","request_id":"<uuid>","payload":{<openai-shape>}}
    {"type":"response","request_id":"<uuid>","error":"<str>"}
    {"type":"ping"}     # heartbeat
    {"type":"hello","sdk_version":"…","backends":["lmstudio"]}  # one-shot

The worker authenticates with the user's CRP Comply API key (same one
used for REST). We never accept a per-message ``user_id`` — it is
derived from the authenticated key and frozen for the socket lifetime.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from .deps import get_auth, get_current_user
from .worker_registry import get_worker_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["worker"])

# Fail hard at import time if the audit signing key is missing.
# Allow a secret persisted by the application lifespan to satisfy this.
_CRP_COMPLY_JWT_SECRET = os.environ.get("CRP_COMPLY_JWT_SECRET")
if not _CRP_COMPLY_JWT_SECRET:
    from pathlib import Path

    _data_dir = Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
    _secret_file = _data_dir / ".jwt_secret"
    if _secret_file.exists():
        _CRP_COMPLY_JWT_SECRET = _secret_file.read_text(encoding="utf-8").strip()

if not _CRP_COMPLY_JWT_SECRET:
    raise RuntimeError(
        "CRP_COMPLY_JWT_SECRET environment variable is required. "
        "Set it to a cryptographically secure random string before starting."
    )


@router.websocket("/agent/worker")
async def worker_socket(websocket: WebSocket) -> None:
    """SDK worker connects here. One socket per user."""
    # Auth: API key via ``Authorization: Bearer crp_…`` header ONLY.
    api_key = None
    auth_hdr = websocket.headers.get("authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        api_key = auth_hdr.split(" ", 1)[1].strip()
    if not api_key:
        await websocket.close(code=4401, reason="Authorization: Bearer required")
        return

    auth = get_auth()
    res = auth.verify_api_key(api_key)
    if res is None:
        await websocket.close(code=4401, reason="invalid api_key")
        return
    user_id, _tier = res

    await websocket.accept()

    # Origin validation (SPEC-015 §5)
    _allowed_origins = {
        origin.strip()
        for origin in os.environ.get(
            "CRP_WORKER_ALLOWED_ORIGINS",
            "https://comply.crprotocol.io,https://gateway.crprotocol.io,"
            "http://localhost:5173,http://localhost:3000",
        ).split(",")
        if origin.strip()
    }
    origin = websocket.headers.get("origin")
    if origin and origin not in _allowed_origins:
        logger.warning("WebSocket origin rejected: %s", origin)
        await websocket.close(code=1008, reason="origin not allowed")
        return

    await websocket.send_json(
        {
            "type": "ready",
            "v": 1,
            "user_id_hash": _hash(user_id),
        }
    )

    reg = get_worker_registry()
    await reg.attach(user_id, websocket)
    # WS-GAP-2: audit the worker connection so the compliance trail records
    # which user activated a local-LLM relay, and when.
    _audit_ws_event(user_id, "worker_connected")
    try:
        while True:
            try:
                message = await websocket.receive_json()
            except ValueError:
                # Bad JSON — ignore but keep socket open.
                continue
            await reg.receive(user_id, message)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("worker socket error for %s: %s", _hash(user_id), exc)
    finally:
        await reg.detach(user_id)
        # WS-GAP-2: audit the disconnection.
        _audit_ws_event(user_id, "worker_disconnected")


@router.get("/agent/worker/status")
async def worker_status(
    user_id: Annotated[str, Depends(get_current_user)],
) -> dict[str, object]:
    """Return whether the calling user has a worker attached right now.

    Frontend uses this to render the green dot next to "Local via SDK
    worker" in Settings, and to gate the Connect button.
    """
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    reg = get_worker_registry()
    snap = reg.status(user_id)
    if snap is None:
        return {"attached": False}
    return snap


def _hash(user_id: str) -> str:
    if len(user_id) <= 12:
        return user_id
    return f"{user_id[:8]}…"


def _audit_ws_event(user_id: str, event: str) -> None:
    """WS-GAP-2: record WebSocket worker connect/disconnect in the audit trail.

    Failures are logged at ERROR — an unavailable audit library must never
    prevent the socket from operating, but we must not swallow faults silently.
    """
    try:
        from crp.security import ComplianceAuditTrail as _WSAT, ComplianceEventType as _WSCET

        _trail = _WSAT(
            signing_key=_CRP_COMPLY_JWT_SECRET.encode(),
            session_id=f"worker:{_hash(user_id)}",
        )
        _trail.record(
            event_type=_WSCET.DATA_PROCESSED,
            session_id=f"worker:{_hash(user_id)}",
            data={"event": event, "user_id_hash": _hash(user_id)},
        )
    except Exception:  # pragma: no cover
        logger.error("WS audit trail failure for %s", _hash(user_id), exc_info=True)


__all__ = ["router"]
