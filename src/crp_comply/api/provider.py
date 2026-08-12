# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""LLM provider configuration — per-user upstream key management.

Allows users to configure their LLM provider (OpenAI / Anthropic / custom)
through the web UI instead of requiring env vars.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..persistent_json_store import JsonStore, get_json_store
from .deps import get_current_user, meter_call
from .llm_security import is_self_hosted_deployment, validate_local_llm_url

logger = logging.getLogger("crp_comply.api.provider")

router = APIRouter(prefix="/llm", tags=["provider"])

# ── Models ─────────────────────────────────────────────────────


class ProviderConfigRequest(BaseModel):
    """Configure an upstream LLM provider."""

    provider: str = Field(
        ...,
        pattern=r"^(openai|anthropic|deepinfra|lmstudio|ollama|custom|local_worker)$",
        description="Provider name",
    )
    api_key: str = Field(
        default="local",
        min_length=1,
        max_length=256,
        description=(
            "Provider API key. For local providers (LM Studio, Ollama) "
            "pass any non-empty placeholder \u2014 the upstream won't validate it."
        ),
    )
    base_url: str | None = Field(
        None,
        max_length=512,
        description="Custom base URL (required for 'custom' provider, optional for others)",
    )
    model: str | None = Field(
        None,
        max_length=128,
        description="Preferred model name (e.g. gpt-4o, claude-sonnet-4-20250514, llama3.1:8b)",
    )
    dispatch_mode: str | None = Field(
        None,
        pattern=r"^(agentic|with_tools|stream_augmented|plain)?$",
        description=(
            "CRP agent dispatch mode. Leave empty (default) for the iterative "
            "domain-tool loop (recommended for compliance reports). "
            "Set to 'agentic' to use the CRP §22 native cognitive loop."
        ),
    )


class ProviderConfigResponse(BaseModel):
    """Response after configuring a provider."""

    configured: bool
    provider: str
    base_url: str
    model: str | None = None
    configured_at: str


class ProviderTestResponse(BaseModel):
    """Response from testing the LLM connection."""

    success: bool
    provider: str
    base_url: str
    models: list[str] = []
    latency_ms: int = 0
    error: str | None = None


class ProviderStatusResponse(BaseModel):
    """Current provider configuration status."""

    configured: bool
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    configured_at: str | None = None
    source: str = "none"  # "user", "env", "none"
    dispatch_mode: str | None = None


class ProviderContextResponse(BaseModel):
    """Provider context metadata including the resolved context window."""

    provider: str
    base_url: str | None = None
    model: str | None = None
    context_window: int | None = None
    source: str


# ── Provider Storage ───────────────────────────────────────────

_PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    # DeepInfra exposes an OpenAI-compatible surface at /v1/openai. Cheap
    # hosted Llama / Mistral / Qwen — popular BYOK choice for cost-sensitive
    # tenants who don't want to run their own GPU box.
    "deepinfra": "https://api.deepinfra.com/v1/openai",
    "lmstudio": "http://localhost:1234/v1",
    "ollama": "http://localhost:11434/v1",
    "custom": "",
}


class ProviderStore:
    """Encrypted storage for per-user LLM provider configs.

    Stores provider type + base URL in plaintext, API keys as
    reversible encrypted blobs (AES-256-GCM via CRP StateEncryptor
    if available, otherwise XOR-obfuscated with HMAC verification).

    Backed by :mod:`crp_comply.persistent_json_store` so the store
    survives Railway/fly.io redeploys when Redis is enabled.
    """

    _STORE_KEY = "provider_configs"

    def __init__(
        self, data_dir: Path | str | None = None, secret: str = "", store: JsonStore | None = None
    ) -> None:
        self._store = store or get_json_store("provider_configs", data_dir)
        self._secret = secret or os.environ.get("CRP_COMPLY_JWT_SECRET", "dev")
        self._configs: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        raw = self._store.get(self._STORE_KEY)
        if isinstance(raw, dict):
            self._configs = raw

    def _save(self) -> None:
        self._store.set(self._STORE_KEY, self._configs)

    @staticmethod
    def _derive_key(secret: str, salt: str) -> bytes:
        """Derive a 32-byte key from secret + salt."""
        return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt.encode(), 100_000, dklen=32)

    def _fernet(self, user_id: str):
        """Build a per-user Fernet key from the master secret + user salt."""
        import base64
        from cryptography.fernet import Fernet

        dk = self._derive_key(self._secret, user_id)
        return Fernet(base64.urlsafe_b64encode(dk))

    def _encrypt_key(self, api_key: str, user_id: str) -> str:
        """Encrypt an API key for storage using AES-128-CBC + HMAC-SHA256 (Fernet).

        Format: ``fer:<token>`` (Fernet token, URL-safe base64).

        If ``CRP_COMPLY_KEK_CHAIN`` is configured, the Fernet token is
        additionally wrapped with the rotating key-encryption key so we
        can silently rotate the master secret without rewriting every
        tenant's BYOK key (PRODUCT_SECURITY.md §4 gap #6).
        """
        token = self._fernet(user_id).encrypt(api_key.encode()).decode()
        stored = "fer:" + token

        # Opportunistic KEK wrap — only when an operator has configured
        # a rotation chain. Absent chain ⇒ legacy format (back-compat).
        try:
            from . import kek as _kek

            if os.environ.get("CRP_COMPLY_KEK_CHAIN"):
                return "kek:" + _kek.seal(stored)
        except Exception as _kek_exc:  # pragma: no cover — KEK is best-effort
            logger.debug(
                "swallowed in provider._encrypt_key (KEK best-effort): %s",
                _kek_exc,
            )
        return stored

    def _decrypt_key(self, stored: str, user_id: str) -> str:
        """Decrypt a stored API key.

        Transparently handles wrapped + bare formats:
          * ``kek:v{n}.<nonce>.<ct>`` — KEK-wrapped envelope
          * ``fer:<fernet-token>``    — Fernet AEAD (current default)
          * raw hex                   — legacy XOR (best-effort recovery)
          * ``<hex>:<tag>``           — legacy XOR-with-tag
        """
        if stored.startswith("kek:"):
            try:
                from . import kek as _kek

                stored, _version = _kek.open_envelope(stored[4:])
            except Exception as exc:  # pragma: no cover
                raise RuntimeError(f"KEK unwrap failed for user {user_id}: {exc}") from exc

        if stored.startswith("fer:"):
            return self._fernet(user_id).decrypt(stored[4:].encode()).decode()

        # Legacy XOR fallback (kept for migration safety; no production data
        # used this path because the prior implementation referenced a
        # non-existent ``hashlib.hmac_new`` and would have raised on write).
        parts = stored.split(":", 1)
        encrypted = bytes.fromhex(parts[0])
        dk = self._derive_key(self._secret, user_id)
        return bytes(b ^ dk[i % len(dk)] for i, b in enumerate(encrypted)).decode()

    def get(self, user_id: str) -> dict[str, Any] | None:
        """Get provider config for a user (with decrypted key)."""
        cfg = self._configs.get(user_id)
        if not cfg:
            return None
        result = dict(cfg)
        result["api_key"] = self._decrypt_key(cfg["api_key_enc"], user_id)
        del result["api_key_enc"]
        return result

    def set(
        self,
        user_id: str,
        provider: str,
        api_key: str,
        base_url: str,
        model: str | None = None,
        dispatch_mode: str | None = None,
    ) -> dict[str, Any]:
        """Store provider config for a user."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        self._configs[user_id] = {
            "provider": provider,
            "api_key_enc": self._encrypt_key(api_key, user_id),
            "base_url": base_url,
            "model": model,
            "configured_at": now,
            "dispatch_mode": dispatch_mode or "",
        }
        self._save()
        return {
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "configured_at": now,
        }

    def delete(self, user_id: str) -> bool:
        """Remove provider config for a user."""
        if user_id in self._configs:
            del self._configs[user_id]
            self._save()
            return True
        return False


# ── Singleton ──────────────────────────────────────────────────

_store: ProviderStore | None = None


def init_provider_store(data_dir: Path | str | None = None, secret: str = "") -> None:
    """Initialise the provider store singleton."""
    global _store
    _store = ProviderStore(data_dir=data_dir, secret=secret)


def get_provider_store() -> ProviderStore:
    if _store is None:
        raise RuntimeError("Provider store not initialised")
    return _store


def get_user_upstream(user_id: str) -> tuple[str, str] | None:
    """Get (upstream_url, upstream_key) for a user, or None.

    Used by the proxy to resolve per-user upstream credentials.
    """
    if _store is None:
        return None
    cfg = _store.get(user_id)
    if not cfg:
        return None
    return cfg["base_url"], cfg["api_key"]


# ── Routes ─────────────────────────────────────────────────────


@router.post("/configure", response_model=ProviderConfigResponse)
async def configure_provider(
    req: ProviderConfigRequest,
    user_id: str = Depends(get_current_user),
):
    """Configure the upstream LLM provider for the current user.

    For local providers (LM Studio / Ollama / custom OpenAI-compatible) we
    probe the endpoint *before* persisting the config so the user gets an
    immediate, actionable error instead of a silent success that fails on
    the first inference call.
    """
    store = get_provider_store()

    # local_worker has no base_url — the worker is identified by the user's
    # API key over the WebSocket relay. Persist a synthetic record and exit.
    if req.provider == "local_worker":
        from .worker_registry import get_worker_registry

        attached = get_worker_registry().is_attached(user_id)
        store.set(
            user_id,
            provider="local_worker",
            api_key="local-worker",
            base_url="ws://relay/agent/worker",
            model=req.model or os.environ.get("CRP_COMPLY_LOCAL_MODEL", "auto"),
            dispatch_mode=req.dispatch_mode or "",
        )
        rec = store.get(user_id)
        return ProviderConfigResponse(
            configured=True,
            provider="local_worker",
            base_url="(SDK worker relay)" + ("" if attached else " — worker not connected yet"),
            model=rec["model"] if rec else None,
            configured_at=rec["configured_at"] if rec else "",
        )

    base_url = req.base_url or _PROVIDER_DEFAULTS.get(req.provider, "")
    if req.provider == "custom" and not base_url:
        raise HTTPException(400, "Custom provider requires a base_url")

    # Forgiving normalisation: LM Studio's OpenAI-compat surface lives under
    # /v1, but users routinely paste the bare host:port. Append it for them.
    if req.provider == "lmstudio" and base_url and not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    if req.provider == "ollama" and base_url and not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    # Probe local endpoints before storing — fail loudly with the upstream
    # error rather than silently persisting a broken config. DeepInfra is
    # included here too because its OpenAI-compat /models endpoint validates
    # the API key cheaply (200 with key list / 401 without) so we can give
    # the user immediate feedback on a bad token.
    if req.provider in ("lmstudio", "ollama", "custom", "deepinfra"):
        # If CRP Comply itself is hosted (Railway, Fly, etc.) the API server
        # *cannot* reach private-network addresses on the user's LAN. Detect
        # that up-front and tell the user, rather than waiting 8s for the TCP
        # SYN to be silently dropped by the cloud network.
        try:
            validate_local_llm_url(base_url, provider=req.provider)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        if req.provider in ("lmstudio", "ollama") and not is_self_hosted_deployment():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{req.provider} can only be used in self-hosted deployments. "
                    "Use the SDK worker relay or a hosted provider."
                ),
            )

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                models_url = base_url.rstrip("/") + "/models"
                resp = await client.get(
                    models_url,
                    headers={"Authorization": f"Bearer {req.api_key}"},
                )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Could not reach {req.provider} at {base_url}. "
                        f"Upstream returned HTTP {resp.status_code}. "
                        f"Check the base URL is correct and the server is running."
                    ),
                )
        except HTTPException:
            raise
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Could not connect to {req.provider} at {base_url}. "
                    f"Is the server running and reachable from this host? "
                    f"({type(exc).__name__})"
                ),
            ) from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Timed out connecting to {req.provider} at {base_url} "
                    f"after 8s. The host may be unreachable from the API server."
                ),
            ) from exc
        except Exception as exc:  # pragma: no cover — defensive
            raise HTTPException(
                status_code=502,
                detail=f"Probe failed: {type(exc).__name__}: {str(exc)[:200]}",
            ) from exc

    result = store.set(
        user_id=user_id,
        provider=req.provider,
        api_key=req.api_key,
        base_url=base_url,
        model=req.model,
        dispatch_mode=req.dispatch_mode or "",
    )

    return ProviderConfigResponse(
        configured=True,
        provider=result["provider"],
        base_url=result["base_url"],
        model=result.get("model"),
        configured_at=result["configured_at"],
    )


@router.post("/test", response_model=ProviderTestResponse)
async def test_provider(
    user_id: str = Depends(get_current_user),
):
    """Test the configured LLM provider connection."""
    store = get_provider_store()
    cfg = store.get(user_id)

    # Fall back to env var
    if not cfg:
        env_key = os.environ.get("CRP_COMPLY_UPSTREAM_API_KEY", "")
        env_url = os.environ.get("CRP_COMPLY_UPSTREAM_URL", "https://api.openai.com/v1")
        if env_key:
            cfg = {
                "provider": "openai",
                "api_key": env_key,
                "base_url": env_url,
                "model": None,
            }

    if not cfg:
        return ProviderTestResponse(
            success=False,
            provider="none",
            base_url="",
            error="No LLM provider configured. Use the setup wizard to connect one.",
        )

    # Special-case the SDK worker relay: there is no HTTP base_url to probe.
    if cfg["provider"] == "local_worker":
        from .worker_registry import get_worker_registry

        reg = get_worker_registry()
        if not reg.is_attached(user_id):
            return ProviderTestResponse(
                success=False,
                provider="local_worker",
                base_url="(SDK worker relay)",
                error=(
                    "No SDK worker is connected. Run "
                    "`crp-comply worker --lmstudio http://localhost:1234 "
                    "--api-key <your-key>` on the machine hosting your LLM."
                ),
            )
        snap = reg.status(user_id)
        if not snap or not snap.get("llm_reachable"):
            return ProviderTestResponse(
                success=False,
                provider="local_worker",
                base_url="(SDK worker relay)",
                error=snap.get("llm_error")
                if snap
                else "Worker attached but local LLM is not reachable.",
            )
        return ProviderTestResponse(
            success=True,
            provider="local_worker",
            base_url="(SDK worker relay)",
            models=snap.get("llm_models", []),
            latency_ms=0,
        )

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if cfg["provider"] == "anthropic":
                resp = await client.get(
                    f"{cfg['base_url']}/v1/models",
                    headers={
                        "x-api-key": cfg["api_key"],
                        "anthropic-version": "2023-06-01",
                    },
                )
            else:
                models_url = cfg["base_url"].rstrip("/") + "/models"
                resp = await client.get(
                    models_url,
                    headers={"Authorization": f"Bearer {cfg['api_key']}"},
                )

        elapsed = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            data = resp.json()
            model_ids = []
            if "data" in data:
                model_ids = [m.get("id", "") for m in data["data"][:10]]
            return ProviderTestResponse(
                success=True,
                provider=cfg["provider"],
                base_url=cfg["base_url"],
                models=model_ids,
                latency_ms=elapsed,
            )
        else:
            return ProviderTestResponse(
                success=False,
                provider=cfg["provider"],
                base_url=cfg["base_url"],
                latency_ms=elapsed,
                error=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return ProviderTestResponse(
            success=False,
            provider=cfg["provider"],
            base_url=cfg["base_url"],
            latency_ms=elapsed,
            error=str(exc)[:200],
        )


@router.get("/status", response_model=ProviderStatusResponse)
async def provider_status(
    user_id: str = Depends(get_current_user),
):
    """Get the current LLM provider configuration status."""
    store = get_provider_store()
    cfg = store.get(user_id)

    if cfg:
        base_url = cfg["base_url"]
        if cfg["provider"] == "local_worker":
            base_url = "(SDK worker relay)"
        return ProviderStatusResponse(
            configured=True,
            provider=cfg["provider"],
            base_url=base_url,
            model=cfg.get("model"),
            configured_at=cfg.get("configured_at"),
            source="user",
            dispatch_mode=cfg.get("dispatch_mode") or None,
        )

    # Check env var fallback. IMPORTANT: an instance-wide env-configured
    # provider applies to *every* tenant on this deployment, so on the
    # multi-tenant SaaS we must not flag it as the per-user "configured"
    # state — that would unlock LLM-gated UI for users who haven't set up
    # BYOK and would falsely report another user's worker/provider as
    # theirs (cross-user state leak). We only surface the env source when
    # the operator explicitly opts in via ``CRP_COMPLY_EXPOSE_ENV_LLM=1``
    # (typical for self-hosted single-tenant Docker deploys).
    expose_env = (
        os.environ.get("CRP_COMPLY_EXPOSE_ENV_LLM", "").lower() in ("1", "true", "yes")
        or is_self_hosted_deployment()
    )
    # Look at BOTH env-var conventions:
    #   - CRP_COMPLY_LLM_BASE_URL/API_KEY/MODEL  (used by ComplianceLLM autodetect)
    #   - CRP_COMPLY_UPSTREAM_URL/API_KEY        (legacy proxy-relay vars)
    # Either being set is enough to consider the operator's env-LLM live.
    llm_key = os.environ.get("CRP_COMPLY_LLM_API_KEY", "")
    llm_url = os.environ.get("CRP_COMPLY_LLM_BASE_URL", "")
    llm_model = os.environ.get("CRP_COMPLY_LLM_MODEL", "")
    legacy_key = os.environ.get("CRP_COMPLY_UPSTREAM_API_KEY", "")
    legacy_url = os.environ.get("CRP_COMPLY_UPSTREAM_URL", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    env_key_present = bool(llm_key or legacy_key or anthropic_key or openai_key)
    if env_key_present and expose_env:
        if llm_url:
            base_url = llm_url
            provider_name = "openai"
        elif anthropic_key:
            base_url = "https://api.anthropic.com"
            provider_name = "anthropic"
        elif legacy_url:
            base_url = legacy_url
            provider_name = "openai"
        else:
            base_url = "https://api.openai.com/v1"
            provider_name = "openai"
        return ProviderStatusResponse(
            configured=True,
            provider=provider_name,
            base_url=base_url,
            model=llm_model or None,
            source="env",
        )

    return ProviderStatusResponse(configured=False, source="none")


def _resolve_active_provider(user_id: str) -> dict[str, Any] | None:
    """Resolve the active provider for *user_id*, honouring source precedence.

    Returns ``None`` when no per-user config exists and the env-based
    provider is not exposed (multi-tenant SaaS default).
    """
    store = get_provider_store()
    cfg = store.get(user_id)
    if cfg:
        return {
            "source": "user",
            "provider": cfg["provider"],
            "base_url": cfg.get("base_url"),
            "model": cfg.get("model"),
        }

    # Same exposure rule as provider_status: don't leak the operator's
    # env-LLM to tenants unless explicitly opted in or self-hosted.
    expose_env = (
        os.environ.get("CRP_COMPLY_EXPOSE_ENV_LLM", "").lower() in ("1", "true", "yes")
        or is_self_hosted_deployment()
    )
    llm_key = os.environ.get("CRP_COMPLY_LLM_API_KEY", "")
    llm_url = os.environ.get("CRP_COMPLY_LLM_BASE_URL", "")
    llm_model = os.environ.get("CRP_COMPLY_LLM_MODEL", "")
    legacy_key = os.environ.get("CRP_COMPLY_UPSTREAM_API_KEY", "")
    legacy_url = os.environ.get("CRP_COMPLY_UPSTREAM_URL", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    env_key_present = bool(llm_key or legacy_key or anthropic_key or openai_key)
    if env_key_present and expose_env:
        if llm_url:
            base_url = llm_url
            provider_name = "openai"
        elif anthropic_key:
            base_url = "https://api.anthropic.com"
            provider_name = "anthropic"
        elif legacy_url:
            base_url = legacy_url
            provider_name = "openai"
        else:
            base_url = "https://api.openai.com/v1"
            provider_name = "openai"
        return {
            "source": "env",
            "provider": provider_name,
            "base_url": base_url,
            "model": llm_model or None,
        }

    return None


@router.get(
    "/context",
    response_model=ProviderContextResponse,
    summary="Get provider context metadata",
    dependencies=[Depends(meter_call("llm-context-probe"))],
)
async def provider_context(
    user_id: str = Depends(get_current_user),
):
    """Return provider context metadata, including the resolved context window."""
    resolved = _resolve_active_provider(user_id)
    if resolved is None:
        return ProviderContextResponse(
            provider="none",
            base_url=None,
            model=None,
            context_window=None,
            source="none",
        )

    provider = resolved["provider"]
    base_url = resolved["base_url"]
    model = resolved["model"]
    source = resolved["source"]
    context_window: int | None = None

    if provider == "local_worker":
        from .worker_registry import get_worker_registry

        snap = get_worker_registry().status(user_id) or {}
        mctx = snap.get("llm_model_context") or {}
        if model and isinstance(mctx.get(model), int):
            context_window = mctx[model]
        elif mctx:
            context_window = min(mctx.values())
    else:
        try:
            from ..agent.llm import ComplianceLLM

            llm = ComplianceLLM.for_user(user_id)
            context_window = llm.probe_loaded_context_length()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not probe context window for %s: %s", user_id, exc)

    if context_window is None:
        try:
            context_window = max(1024, int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192")))
        except (TypeError, ValueError):
            context_window = 8192

    return ProviderContextResponse(
        provider=provider,
        base_url=base_url,
        model=model,
        context_window=context_window,
        source=source,
    )


@router.get(
    "/diagnose",
    dependencies=[Depends(meter_call("llm-diagnose"))],
)
async def provider_diagnose(
    user_id: str = Depends(get_current_user),
):
    """Diagnose what provider the agent will actually use for THIS user.

    This is the missing observability piece for the recurring
    "I set CRP_COMPLY_LLM_BASE_URL on Railway but the agent still 503s"
    confusion. It returns:

    * source: "user" | "env" | "none"
    * provider: openai / anthropic / deepinfra / lmstudio / ...
    * base_url: what the autodetect resolved to
    * model: what model the autodetect resolved to
    * env_vars_seen: which CRP_COMPLY_LLM_* vars are set (key presence,
      not values — never echo secrets)
    * live_probe: result of an actual 1-token chat call against the
      resolved provider — this is the only way to definitively answer
      "is the LLM actually reachable from this deployment?".

    Safe to call from the Settings page; never exposes API keys.
    """
    store = get_provider_store()
    cfg = store.get(user_id)
    seen = {
        "CRP_COMPLY_LLM_BASE_URL": bool(os.environ.get("CRP_COMPLY_LLM_BASE_URL")),
        "CRP_COMPLY_LLM_API_KEY": bool(os.environ.get("CRP_COMPLY_LLM_API_KEY")),
        "CRP_COMPLY_LLM_MODEL": bool(os.environ.get("CRP_COMPLY_LLM_MODEL")),
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
        "DEEPINFRA_API_KEY": bool(os.environ.get("DEEPINFRA_API_KEY")),
        "GROQ_API_KEY": bool(os.environ.get("GROQ_API_KEY")),
        "TOGETHER_API_KEY": bool(os.environ.get("TOGETHER_API_KEY")),
        "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY")),
    }

    # ── Live probe ────────────────────────────────────────────────
    # Build the same ComplianceLLM the public assessment narrative uses
    # and fire a 1-token "ping" to surface the *actual* upstream error
    # (401 invalid key, 404 model not found, connect timeout, etc.).
    # Without this, the only signal users get is "fallback narrative",
    # which leaves them guessing.
    def _probe(user_id: str | None = None) -> dict:
        try:
            from ..agent.llm import ComplianceLLM

            if user_id:
                llm = ComplianceLLM.for_user(user_id, default_max_tokens=8)
            else:
                llm = ComplianceLLM(default_max_tokens=8)
            t0 = time.time()
            text = llm.chat(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
            )
            return {
                "ok": True,
                "latency_ms": int((time.time() - t0) * 1000),
                "sample": (text or "").strip()[:120],
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "latency_ms": None,
                "sample": None,
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            }

    if cfg and cfg.get("provider") == "local_worker":
        from .worker_registry import get_worker_registry

        reg = get_worker_registry()
        snap = reg.status(user_id) or {}
        return {
            "source": "user",
            "provider": "local_worker",
            "base_url": "(SDK worker relay)",
            "model": cfg.get("model"),
            "env_vars_seen": seen,
            "live_probe": {
                "ok": bool(snap.get("llm_reachable")),
                "latency_ms": None,
                "sample": None,
                "error": snap.get("llm_error")
                or (None if snap.get("attached") else "SDK worker not connected"),
            },
            "worker_status": {
                "attached": bool(snap.get("attached")),
                "llm_reachable": snap.get("llm_reachable"),
                "models": snap.get("llm_models") or [],
                "model_context": snap.get("llm_model_context") or {},
            },
            "note": (
                "Local-worker provider uses the SDK WebSocket relay. "
                "The live probe reflects the worker's last health frame."
            ),
        }

    if cfg:
        live = _probe(user_id)
        return {
            "source": "user",
            "provider": cfg["provider"],
            "base_url": cfg.get("base_url"),
            "model": cfg.get("model"),
            "env_vars_seen": seen,
            "live_probe": live,
            "note": (
                "Per-user BYOK config takes precedence over env vars. "
                "Use DELETE /api/v1/llm/configure to clear it and fall back "
                "to env-based autodetect."
            ),
        }
    # No user config — what would env autodetect resolve to?
    base_url = os.environ.get("CRP_COMPLY_LLM_BASE_URL")
    if base_url:
        live = _probe()
        return {
            "source": "env",
            "provider": "openai",  # OpenAI-compatible
            "base_url": base_url,
            "model": os.environ.get("CRP_COMPLY_LLM_MODEL", "llama-3.3-70b-versatile"),
            "env_vars_seen": seen,
            "live_probe": live,
            "note": (
                "Env autodetect picked CRP_COMPLY_LLM_BASE_URL. If the live "
                "probe failed, check the error string: 401 = wrong API key, "
                "404 = wrong model name (DeepInfra wants 'meta-llama/Llama-3.3-70B-Instruct-Turbo'), "
                "ConnectError = wrong base URL "
                "(DeepInfra wants 'https://api.deepinfra.com/v1/openai' WITH "
                "'/v1/openai', not just '/v1')."
            ),
        }
    if os.environ.get("ANTHROPIC_API_KEY"):
        live = _probe()
        return {
            "source": "env",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "model": os.environ.get("CRP_COMPLY_LLM_MODEL", "claude-sonnet-4-20250514"),
            "env_vars_seen": seen,
            "live_probe": live,
        }
    if os.environ.get("OPENAI_API_KEY"):
        live = _probe()
        return {
            "source": "env",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": os.environ.get("CRP_COMPLY_LLM_MODEL", "gpt-4o-mini"),
            "env_vars_seen": seen,
            "live_probe": live,
        }
    return {
        "source": "none",
        "provider": None,
        "base_url": None,
        "model": None,
        "env_vars_seen": seen,
        "live_probe": {
            "ok": False,
            "latency_ms": None,
            "sample": None,
            "error": "no provider configured",
        },
        "note": (
            "No LLM provider configured. Either configure one in Settings "
            "(BYOK) or set CRP_COMPLY_LLM_BASE_URL + CRP_COMPLY_LLM_API_KEY "
            "(plus optional CRP_COMPLY_LLM_MODEL) in your deployment env."
        ),
    }


@router.delete("/configure")
async def remove_provider(
    user_id: str = Depends(get_current_user),
):
    """Remove the configured LLM provider for the current user."""
    store = get_provider_store()
    removed = store.delete(user_id)
    return {"removed": removed}


@router.post("/rotate")
async def rotate_provider_key(
    user_id: str = Depends(get_current_user),
):
    """Invalidate the current BYOK LLM key.

    Addresses PRODUCT_SECURITY.md §4 gap #3: BYOK key rotation flow.

    This deletes the stored key + configuration; the user is then expected
    to immediately re-``POST /llm/configure`` with the newly-issued key
    from their upstream provider. Returns the wiped metadata so the
    frontend can pre-fill ``provider`` / ``base_url`` / ``model`` fields.
    """
    store = get_provider_store()
    current = store.get(user_id)
    store.delete(user_id)
    if current is None:
        return {"rotated": False, "reason": "no_config_present"}
    return {
        "rotated": True,
        "previous": {
            "provider": current.get("provider"),
            "base_url": current.get("base_url"),
            "model": current.get("model"),
            "configured_at": current.get("configured_at"),
        },
        "next_action": "POST /llm/configure with your freshly-issued key",
    }
