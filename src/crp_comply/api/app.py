# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply — FastAPI application factory."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..core import CRPComply
from ..gateway_proxy import ComplyGatewayProxy, GatewayProxyError
from ..header_mapping import map_response_headers
from ..proxy import ComplianceInterceptor, init_proxy
from ..proxy import router as proxy_router
from ..continuous_compliance import get_engine as get_cc_engine, init_engine as init_cc_engine
from .agent import init_agent_sessions
from .agent import router as agent_router
from .auth import AuthManager
from .billing import _init_stripe
from .billing import router as billing_router
from .continuous import init_continuous_engine, router as continuous_router
from .github_routes import router as github_router
from .deps import init_dependencies, init_passkey_manager
from .provider import init_provider_store
from .provider import router as provider_router
from .public import router as public_router
from .recipes import router as recipes_router
from .search import router as search_router
from .artefacts import init_artefact_store, router as artefacts_router
from .notifications import router as notifications_router
from .persistence_probe import probe_volume, record_status
from .reports import init_report_store
from .routes import router as api_router, passkey_router as comply_passkey_router
from .sdk import router as sdk_router
from .corpus_routes import router as corpus_router
from .session_routes import router as session_router
from .session_store import init_session_store
from .usage import init_usage_tracker
from .worker_ws import router as worker_router
from .well_known import well_known_router, settings_router
from .webhooks import verify_signature

logger = logging.getLogger("crp_comply.api")

# Shared PostgreSQL pool reference set during lifespan; used by webhook handlers
# that need to persist Gateway audit events without re-initialising the pool.
_comply_pool: Any | None = None

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise singletons on startup, cleanup on shutdown."""
    import asyncio

    data_dir = Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
    jwt_secret = os.environ.get("CRP_COMPLY_JWT_SECRET")
    secret_file = data_dir / ".jwt_secret"

    if jwt_secret:
        # Persist explicit secret so restarts can fall back to the file.
        data_dir.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(jwt_secret, encoding="utf-8")
    elif secret_file.exists():
        jwt_secret = secret_file.read_text(encoding="utf-8").strip()

    if not jwt_secret:
        raise RuntimeError(
            "CRP_COMPLY_JWT_SECRET is not set and no persisted JWT secret was found. "
            "Set CRP_COMPLY_JWT_SECRET in the environment."
        )

    # Volume persistence probe — must run BEFORE anything writes to data_dir
    # so we capture the "fresh filesystem?" state accurately.
    probe_status = probe_volume(data_dir)
    record_status(probe_status)

    # Initialise the session store on the attached volume before auth wiring
    # so HttpOnly session cookies survive Redis restarts and redeploys.
    init_session_store(data_dir)

    auth = AuthManager(data_dir=data_dir, jwt_secret=jwt_secret)
    comply = CRPComply()

    init_dependencies(auth=auth, comply=comply)

    # Initialise the OpenAI-compatible compliance proxy
    interceptor = ComplianceInterceptor(
        data_dir=data_dir,
        hmac_secret=jwt_secret,
    )
    init_proxy(interceptor)

    # Initialise per-user LLM provider store
    init_provider_store(data_dir=data_dir, secret=jwt_secret)

    # Initialise Stripe billing
    _init_stripe()

    # Initialise shared Redis connection (used for rate limiting, caching)
    try:
        from crp_shared.redis_client import get_redis_client as _get_redis

        _redis = _get_redis()
        if _redis is not None:
            logger.info("Redis connection initialized")
        else:
            logger.info("Redis not configured — using in-memory fallbacks")
    except Exception as exc:
        logger.warning("Redis initialization failed: %s — continuing with in-memory stores", exc)

    global _comply_pool
    # Initialise shared PostgreSQL connection pool
    _comply_pool = None
    try:
        from crp_shared.db import init_db as _init_db
        from crp_shared.db import _pool as _comply_pool_ref

        await _init_db()
        _comply_pool = _comply_pool_ref
        logger.info("PostgreSQL connection pool initialized")
    except Exception as exc:
        logger.warning(
            "PostgreSQL initialization failed: %s — continuing with file-based stores", exc
        )

    # Initialise Gateway audit evidence schema (best-effort).
    try:
        if _comply_pool is not None:
            from ..gateway_audit_store import (
                init_gateway_audit_schema as _init_gateway_audit_schema,
            )

            await _init_gateway_audit_schema(_comply_pool)
            logger.info("Gateway audit schema initialized")
    except Exception as exc:
        logger.warning("Gateway audit schema initialization failed: %s", exc)

    # Initialise passkey MFA manager (best-effort).
    try:
        init_passkey_manager()
    except Exception as exc:
        logger.warning("Passkey manager initialization failed: %s — continuing without MFA", exc)

    # Initialise GitHub repo/scan persistence schema (best-effort; falls back to memory)
    try:
        from .github_store import init_github_schema as _init_github_schema

        await _init_github_schema()
        logger.info("GitHub persistence schema initialized")
    except Exception as exc:
        logger.warning(
            "GitHub persistence schema initialization failed: %s — using in-memory fallback", exc
        )

    # Initialise per-user monthly usage tracker (quota enforcement)
    init_usage_tracker(data_dir=data_dir)

    # Initialise persisted deliverables store (reports + evidence packs)
    init_report_store(data_dir=data_dir)
    init_artefact_store(data_dir=data_dir)

    # Initialise per-user agent session store (Phase 4.6)
    init_agent_sessions(data_dir=data_dir)

    # Initialise programme tracker (Gap #5 — obligation lifecycle states)
    from ..programme import get_programme_store, init_programme_store

    init_programme_store(data_dir=data_dir)

    # Initialise continuous compliance engine (Round 19 — verdict graph + scheduler)
    init_cc_engine(data_dir=data_dir, programme_store=get_programme_store())
    init_continuous_engine(get_cc_engine())

    # Initialise draft-session bridge (Gap #2 — recipe ↔ agent unification)
    from .draft_sessions import init_draft_sessions

    init_draft_sessions(data_dir=data_dir)

    # Initialise tenant-configurable retention policies
    # (PRODUCT_SECURITY.md §4 gap #5).
    from .retention import init_retention_store

    init_retention_store(data_dir=data_dir)
    # Initialise per-tenant contact profile store (BATCH 10 tenant isolation)
    from ..contacts import init_contact_store

    init_contact_store(data_dir=data_dir)
    # Initialise per-tenant organisation profile store (Onboarding bug fix)
    from ..org_profile import init_org_profile_store

    init_org_profile_store(data_dir=data_dir)
    # Initialise persistent in-app notification inbox (survives restarts)
    from ..notifications import init_persistent_inbox

    init_persistent_inbox(
        data_dir=data_dir
    )  # Warm the ed25519 evidence-pack signing key so the first build call
    # doesn't pay the generation cost (PRODUCT_SECURITY.md §4 gap #4).
    try:
        from . import evidence_signing as _es

        _key = _es.load_or_create_keys(data_dir / "reports")
        logger.info(
            "evidence signing key ready: algo=%s fingerprint=%s", _key.algorithm, _key.fingerprint
        )
    except Exception as _exc:
        logger.warning("evidence signing warm-up failed: %s", _exc)

    # Auto-bootstrap the regulation corpus + RAG index if the index is
    # empty (fresh deploy / fresh volume). Three layers of fallback:
    #   1. If `data/rag_index/corpus.sqlite` already has chunks, skip.
    #   2. Else if `corpus/_scraped/` has JSON docs, embed them.
    #   3. Else run the full scrapers (eurlex, nist, intl, iso) to
    #      regenerate `corpus/_scraped/` from the upstream sources, then
    #      embed.
    # All steps run in a background asyncio task so the FastAPI lifespan
    # is never blocked (avoids Railway's 60s healthcheck timeout). The
    # agent's RAG tool gracefully returns 0 hits with a retry hint
    # while the index is still warming.
    # Disabled by setting CRP_COMPLY_RAG_BOOTSTRAP=false.
    if os.environ.get("CRP_COMPLY_RAG_BOOTSTRAP", "true").lower() == "true":

        async def _bootstrap_corpus():
            import asyncio as _asyncio
            from ..agent.corpus import scraped_output_dir
            from ..agent.rag import CorpusIndex, Embedder, build_from_scraped

            try:
                with CorpusIndex() as _ci:
                    _stats = _ci.stats()
                existing = int(_stats.get("total_chunks", 0) or 0)
            except Exception:
                existing = 0

            if existing > 0:
                logger.info("RAG index ready: %d chunks", existing)
                return

            scraped = scraped_output_dir()
            json_files = [p for p in scraped.glob("*.json") if p.name != "manifest.json"]

            if not json_files:
                logger.info(
                    "Regulation corpus missing \u2014 running scrapers "
                    "(eu_ai_act, gdpr, nis2, nist, oecd, coe, uk, edpb). "
                    "This is a one-time per-deploy operation and can take "
                    "5\u201310 minutes."
                )
                try:
                    # Heavy imports deferred until needed.
                    from ..agent.scrapers import eurlex, intl, nist
                    from ..agent.corpus import write_manifest

                    def _scrape_all():
                        docs = []
                        # Each scraper is best-effort; one failure shouldn't
                        # nuke the whole corpus.
                        for name, fn in [
                            ("eu_ai_act", eurlex.scrape_eu_ai_act),
                            ("gdpr", eurlex.scrape_gdpr),
                            ("nis2", eurlex.scrape_nis2),
                        ]:
                            try:
                                docs.append(fn())
                                logger.info("scraped %s ok", name)
                            except Exception as _e:
                                logger.warning("scrape %s failed: %s", name, _e)
                        try:
                            docs.extend(nist.scrape())
                        except Exception as _e:
                            logger.warning("scrape nist failed: %s", _e)
                        try:
                            docs.extend(intl.scrape())
                        except Exception as _e:
                            logger.warning("scrape intl (oecd/coe/uk/edpb) failed: %s", _e)
                        return docs

                    # Run blocking scrape in a thread so the event loop
                    # stays responsive.
                    docs = await _asyncio.to_thread(_scrape_all)
                    if not docs:
                        logger.error("all scrapers failed \u2014 RAG will run empty")
                        return
                    # Persist scraped JSONs.
                    out_dir = scraped
                    for doc in docs:
                        try:
                            doc.write_json(out_dir / f"{doc.source_id}.json")
                        except Exception as _e:
                            logger.warning("write %s failed: %s", doc.source_id, _e)
                    try:
                        write_manifest(docs, out_dir / "manifest.json")
                    except Exception:
                        logger.debug("manifest write failed", exc_info=True)
                    logger.info("scraped %d source(s) \u2192 %s", len(docs), out_dir)
                except Exception:
                    logger.exception("auto-scrape failed")
                    return

            # Embed + index. Heavy: loads sentence-transformers.
            try:
                logger.info(
                    "embedding regulation corpus \u2014 this can take "
                    "1\u20133 minutes on first boot"
                )
                _summary = await _asyncio.to_thread(lambda: build_from_scraped(embedder=Embedder()))
                logger.info(
                    "RAG bootstrap complete: %d chunks across %d sources",
                    _summary.get("total_chunks", 0),
                    len(_summary.get("sources", []) or []),
                )
            except Exception:
                logger.exception("RAG embed/build failed")
                return

            # Phase 6 \u2014 CKF-from-corpus: extract structured facts from
            # every chunk through the CRP ExtractionPipeline so that the
            # CKF (semantic memory) is pre-populated alongside the RAG
            # index. Gated behind CRP_COMPLY_BOOTSTRAP_CKF (default false
            # because GLiNER weights are 200MB+ and extraction over 1.5k
            # chunks takes ~10 minutes). Operators can opt in.
            # Default ON: corpus CKF is the headline differentiator (semantic
            # graph over the regulation, not just embedded chunks). Operators
            # can disable with CRP_COMPLY_BOOTSTRAP_CKF=false on tiny instances.
            if os.environ.get("CRP_COMPLY_BOOTSTRAP_CKF", "true").lower() == "true":
                try:
                    from ..agent.ckf_corpus import (  # type: ignore[import-not-found]
                        bootstrap_ckf_from_corpus,
                    )

                    logger.info(
                        "CKF-from-corpus bootstrap starting (this can take "
                        "5\u201315 minutes on first boot)"
                    )
                    n_facts = await _asyncio.to_thread(bootstrap_ckf_from_corpus)
                    logger.info("CKF bootstrap complete: %d facts seeded", n_facts)
                except Exception:
                    logger.exception("CKF-from-corpus bootstrap failed (non-fatal)")

        asyncio.create_task(_bootstrap_corpus())

    logger.info("CRP Comply API started \u2014 data_dir=%s", data_dir)

    # Background retention + cleanup task (Phase 3.6)

    async def _retention_loop():
        from .reports import get_pack_builder, get_report_store
        from .retention import get_retention_store

        default_report_days = int(os.environ.get("CRP_COMPLY_REPORT_RETENTION_DAYS", "180"))
        default_pack_days = int(os.environ.get("CRP_COMPLY_EVIDENCE_RETENTION_DAYS", "365"))
        interval_seconds = int(os.environ.get("CRP_COMPLY_RETENTION_INTERVAL_SECONDS", "86400"))
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                store = get_report_store()
                pb = get_pack_builder()
                rs = get_retention_store()

                total_reports = total_packs = 0
                users = set()
                try:
                    for p in (data_dir / "reports").iterdir():
                        if p.is_dir():
                            users.add(p.name)
                except FileNotFoundError:
                    pass

                # Per-user sweeps honour each tenant's configured window.
                for user_id in users:
                    policy = rs.get(user_id)
                    # ReportStore.purge_older_than is global today; we fall
                    # back to the default window until it grows a user arg.
                    # Log the per-user target for ops visibility.
                    logger.debug(
                        "retention target user=%s reports=%dd evidence=%dd",
                        user_id,
                        policy.reports_days,
                        policy.evidence_days,
                    )

                total_reports = store.purge_older_than(days=default_report_days)
                total_packs = pb.purge_older_than(days=default_pack_days)
                if total_reports or total_packs:
                    logger.info(
                        "retention sweep: purged %d reports, %d evidence packs",
                        total_reports,
                        total_packs,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("retention sweep failed: %s", exc)

    retention_task: asyncio.Task | None = None
    if os.environ.get("CRP_COMPLY_RETENTION_ENABLED", "true").lower() == "true":
        retention_task = asyncio.create_task(_retention_loop())

    # Phase 4 — continuous regulation corpus ingestion (default OFF to avoid
    # unexpected network traffic; enable in production with
    # CRP_COMPLY_CONTINUOUS_INGEST_ENABLED=true).
    ingest_task: asyncio.Task | None = None
    if os.environ.get("CRP_COMPLY_CONTINUOUS_INGEST_ENABLED", "false").lower() == "true":
        try:
            from ..corpus import IngestionScheduler

            ingest_interval = float(
                os.environ.get("CRP_COMPLY_CONTINUOUS_INGEST_INTERVAL_HOURS", "168")
            )
            ingest_sources = os.environ.get("CRP_COMPLY_CONTINUOUS_INGEST_SOURCES")
            ingest_source_list = (
                [s.strip() for s in ingest_sources.split(",") if s.strip()]
                if ingest_sources
                else None
            )
            scheduler = IngestionScheduler()
            ingest_task = asyncio.create_task(
                scheduler.run_continuous(
                    interval_hours=ingest_interval,
                    source_ids=ingest_source_list,
                )
            )
            logger.info(
                "continuous corpus ingestion started: interval=%.1fh sources=%s",
                ingest_interval,
                ingest_source_list,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("continuous ingestion scheduler not started: %s", exc)

    # In-process nightly backup (replaces a separate cron service —
    # Railway volumes are isolated per service so a sibling service
    # cannot read /app/data). See crp_comply.backup_scheduler.
    backup_task: asyncio.Task | None = None
    try:
        from crp_comply.backup_scheduler import is_enabled, scheduler_loop

        if is_enabled():
            backup_task = asyncio.create_task(scheduler_loop())
    except Exception as exc:  # noqa: BLE001
        logger.warning("backup scheduler not started: %s", exc)

    # Stripe↔local billing reconciliation loop (Round 16).
    billing_reconcile_task: asyncio.Task | None = None
    try:
        from crp_comply.billing.reconciliation import reconcile_billing

        if os.environ.get("CRP_COMPLY_BILLING_RECONCILE_ENABLED", "true").lower() == "true":
            reconcile_interval_hours = int(
                os.environ.get("CRP_COMPLY_BILLING_RECONCILE_INTERVAL_HOURS", "24")
            )

            async def _billing_reconcile_loop() -> None:
                while True:
                    await asyncio.sleep(reconcile_interval_hours * 3600)
                    try:
                        await reconcile_billing(auth)
                    except asyncio.CancelledError:
                        raise
                    except Exception as loop_exc:
                        logger.warning("billing reconciliation failed: %s", loop_exc)

            billing_reconcile_task = asyncio.create_task(_billing_reconcile_loop())
    except Exception as exc:  # noqa: BLE001
        logger.warning("billing reconciliation scheduler not started: %s", exc)

    yield

    if retention_task:
        retention_task.cancel()
        try:
            await retention_task
        except (asyncio.CancelledError, Exception):
            pass
    if backup_task:
        backup_task.cancel()
        try:
            await backup_task
        except (asyncio.CancelledError, Exception):
            pass
    if billing_reconcile_task:
        billing_reconcile_task.cancel()
        try:
            await billing_reconcile_task
        except (asyncio.CancelledError, Exception):
            pass
    if ingest_task:
        ingest_task.cancel()
        try:
            await ingest_task
        except (asyncio.CancelledError, Exception):
            pass
    await interceptor.close()
    logger.info("CRP Comply API shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from crp_comply import __version__

    app = FastAPI(
        title="CRP Comply",
        description=(
            "AI Governance & EU AI Act Compliance Platform — built on the Context Relay Protocol"
        ),
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    # CORS — allow the React frontend
    allowed_origins = os.environ.get(
        "CRP_COMPLY_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Mandatory passkey MFA middleware ──────────────────────
    # MFA is mandatory in production. The kill-switch only works outside
    # production so local integration tests and demos can opt out.
    _app_env = os.environ.get("APP_ENV", "production").lower()
    _passkey_mfa_disabled = _app_env != "production" and os.environ.get(
        "PASSKEY_MFA_DISABLED", ""
    ).lower() in ("true", "1", "yes")

    @app.middleware("http")
    async def _passkey_mfa_middleware(request: Request, call_next):
        """Require a valid passkey MFA session for all Clerk-authenticated API calls.

        API keys and public/webhook/passkey routes are exempt. Set
        ``PASSKEY_MFA_DISABLED=true`` for local demos or integration tests.
        """
        if _passkey_mfa_disabled:
            return await call_next(request)

        path = request.url.path

        if not path.startswith(("/api/v1/", "/v1/")):
            return await call_next(request)

        if path.startswith(
            (
                "/api/v1/public/",
                "/api/v1/passkeys/",
                "/api/v1/auth/session",
                "/api/v1/auth/step-up",
                "/api/github/webhook",
            )
        ):
            return await call_next(request)

        auth = request.headers.get("Authorization") or ""
        x_api_key = request.headers.get("X-Api-Key")
        if x_api_key:
            return await call_next(request)
        if not auth.startswith("Bearer "):
            return await call_next(request)

        token = auth[7:]

        from .deps import get_auth, get_auth_context, get_passkey_manager
        from fastapi.responses import JSONResponse

        manager = get_passkey_manager()
        if manager is None:
            return await call_next(request)

        clerk_claims = get_auth().verify_clerk_token(token)
        if not clerk_claims:
            return await call_next(request)
        sub = clerk_claims.get("sub", "")
        if not sub.startswith("user_"):
            return await call_next(request)
        user_id = f"clerk:{sub}"

        # Before the first passkey is enrolled, the user is still in MFA setup
        # flow. Protected routes needed for onboarding (e.g. /me/org-profile)
        # must remain reachable so the setup page can render and the user can
        # complete enrollment. Once a credential exists, the MFA session token
        # is enforced as usual.
        try:
            if not await manager.has_credentials(user_id):
                return await call_next(request)
        except Exception:
            pass

        mfa_token = request.headers.get("X-Passkey-Mfa-Session")
        if not mfa_token:
            mfa_token = request.cookies.get("crp_passkey_mfa_token")
        context = get_auth_context(request)
        assessment = await manager.verify_mfa_session(mfa_token, user_id, context)

        if assessment is None:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"detail": "Passkey MFA required", "code": "passkey_mfa_required"},
                status_code=403,
            )
        if assessment.decision in ("challenge", "block"):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {
                    "detail": "Passkey step-up required",
                    "code": "passkey_step_up",
                    "risk_score": assessment.score,
                    "risk_factors": assessment.factors,
                },
                status_code=403,
            )

        return await call_next(request)

    # ── Security headers ──────────────────────────────────────
    # Defence-in-depth on top of Cloudflare. Mirrors PRODUCT_SECURITY.md
    # §3 and the OWASP Secure Headers Project. Applied to every response.
    #
    # CSP is the only header that has repeatedly caused production breakage
    # (Clerk satellite domains, Cloudflare beacons, Google Fonts, hashed
    # asset paths). To prevent a recurrence we ship CSP **disabled by
    # default** and rely on Cloudflare WAF + the rest of these headers
    # (HSTS, nosniff, X-Frame-Options=DENY, Referrer-Policy,
    # Permissions-Policy, COOP/CORP) for the OWASP baseline. Operators
    # who want CSP must opt in with ``CRP_COMPLY_CSP_ENABLED=true`` after
    # validating the policy below in their environment.
    csp_enabled = os.environ.get("CRP_COMPLY_CSP_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    @app.middleware("http")
    async def _security_headers(request, call_next):
        response = await call_next(request)
        h = response.headers
        # HSTS — 1 year, include subdomains, eligible for preload list.
        h.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains; preload",
        )
        # Block MIME-sniffing and clickjacking.
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Disable powerful web platform features we do not use.
        h.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(self), usb=(), interest-cohort=()",
        )
        # COOP only — drop CORP because it blocks legitimate CDN-served
        # static assets (CSS / fonts) under Cloudflare's caching layer.
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # Optional CSP — opt-in. Includes:
        #   * Clerk satellite domain (clerk.<your-domain>) used in prod,
        #     plus *.clerk.accounts.dev / *.clerk.com for dev keys.
        #   * Cloudflare Insights beacon (static.cloudflareinsights.com).
        #   * Google Fonts (fonts.googleapis.com + fonts.gstatic.com).
        #   * Stripe (js / api / checkout / hooks).
        #   * Turnstile (challenges.cloudflare.com).
        #   * 'unsafe-eval' for Clerk's wasm + dynamic-eval flows.
        #   * worker-src blob: for Clerk Web Workers.
        if csp_enabled:
            h.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://js.stripe.com "
                "https://*.clerk.accounts.dev https://*.clerk.com "
                "https://clerk.comply.crprotocol.io "
                "https://static.cloudflareinsights.com "
                "https://challenges.cloudflare.com; "
                "script-src-elem 'self' 'unsafe-inline' "
                "https://js.stripe.com "
                "https://*.clerk.accounts.dev https://*.clerk.com "
                "https://clerk.comply.crprotocol.io "
                "https://static.cloudflareinsights.com "
                "https://challenges.cloudflare.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "style-src-elem 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data: blob: https:; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                "worker-src 'self' blob:; "
                "connect-src 'self' "
                "https://*.clerk.accounts.dev https://*.clerk.com "
                "https://clerk.comply.crprotocol.io "
                "https://clerk-telemetry.com https://*.clerk-telemetry.com "
                "https://cloudflareinsights.com "
                "https://api.stripe.com; "
                "frame-src 'self' "
                "https://js.stripe.com https://hooks.stripe.com "
                "https://checkout.stripe.com "
                "https://*.clerk.accounts.dev https://*.clerk.com "
                "https://challenges.cloudflare.com; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self' https://checkout.stripe.com; "
                "object-src 'none';",
            )
        return response

    # Mount API routes
    app.include_router(api_router, prefix="/api/v1")

    # Mount passkey lifecycle routes (not subject to MFA dependency)
    app.include_router(comply_passkey_router, prefix="/api/v1")
    app.include_router(session_router, prefix="/api/v1")

    # Mount Stripe billing routes
    app.include_router(billing_router, prefix="/api/v1")

    # Mount GitHub + Scan + No-Code routes
    app.include_router(github_router, prefix="/api/v1")

    # Legacy GitHub App callback — GitHub Apps often redirect to /api/github/callback
    # (without /v1). This direct route prevents the SPA fallback from catching it.
    from fastapi.responses import RedirectResponse
    from .github_routes import _legacy_github_installed
    from .deps import get_auth
    from crp_comply.github_routes import github_webhook

    @app.get("/api/github/callback", include_in_schema=False)
    async def _api_github_callback(
        installation_id: str | None = None,
        setup_action: str = "install",
        state: str | None = None,
        code: str | None = None,
    ):
        """GitHub App OAuth callback without /v1 prefix.

        Stores the installation_id against the user and redirects back to Comply.
        Security: validates HMAC-signed state first; falls back to raw user_id
        (legacy) with a deprecation warning.
        """
        user_id = ""
        if state:
            try:
                from crp_comply.github_state import verify_state

                payload = verify_state(state)
                user_id = payload.get("clerk_user_id", "")
            except Exception:
                if state.startswith("user_"):
                    user_id = state
                    logger.warning(
                        "Legacy GitHub callback: raw user_id state (deprecated). "
                        "Use /github/connect-start for signed states."
                    )

        if installation_id and user_id:
            try:
                auth = get_auth()
                auth.set_github_installation(user_id, installation_id)
            except Exception:
                pass

        base_url = os.environ.get("APP_BASE_URL", "https://comply.crprotocol.io")
        return RedirectResponse(
            url=f"{base_url}/app/repositories?github_connected=1",
            status_code=302,
        )

    @app.get("/api/github/installed", include_in_schema=False)
    async def _api_github_installed(installation_id: str | None = None):
        """GitHub App installed confirmation without /v1 prefix."""
        return _legacy_github_installed({"installation_id": installation_id or ""})

    @app.post("/api/github/webhook", include_in_schema=False)
    async def _api_github_webhook(request: Request):
        """GitHub App webhook without /v1 prefix."""
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        return github_webhook(body, headers)

    # Mount LLM provider configuration routes
    app.include_router(provider_router, prefix="/api/v1")

    # Mount local-LLM worker WebSocket relay (SDK Mode C)
    app.include_router(worker_router, prefix="/api/v1")

    # Mount SDK gateway (audit, classify, features)
    app.include_router(sdk_router, prefix="/api/v1")

    # Mount compliance agent (Phase 4.6)
    app.include_router(agent_router, prefix="/api/v1")

    # Mount deliverable recipes (Phase 4.7 — DESIGN_GAP §16)
    app.include_router(recipes_router, prefix="/api/v1")

    # Mount Phase 4 corpus admin routes (per-regulation indices, obligations, ingestion jobs)
    app.include_router(corpus_router, prefix="/api/v1")

    # Mount notification multiplexer (BATCH 9 — dynamic agent comms)
    app.include_router(notifications_router, prefix="/api/v1")

    # Mount artefact intake (Layer 2 — user-supplied evidence)
    app.include_router(artefacts_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")

    # Mount public (unauthenticated) funnel routes
    app.include_router(public_router, prefix="/api/v1/public")

    # Mount compliance record endpoints under the API namespace.
    # The OpenAI-compatible /v1 routes are now forwarded to the CRP Gateway.
    app.include_router(proxy_router, prefix="/api/v1")

    # ── CRP Gateway proxy (OpenAI-compatible /v1 routes) ──────
    @app.api_route(
        "/v1/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        include_in_schema=False,
    )
    async def _gateway_proxy(request: Request, path: str) -> Response:
        """Forward all /v1 traffic to the upstream CRP Gateway.

        Customer integrations continue to use ``comply.crprotocol.io/v1``
        as their OpenAI-compatible base_url. Quota gating is applied using
        the tenant resolved from the CRP Comply API key or Clerk org.
        """
        body = await request.body()
        headers = dict(request.headers)

        # Resolve org/tenant for quota gating.
        org_id: str | None = None
        auth_header = headers.get("Authorization", "")
        x_api_key = headers.get("X-Api-Key")
        from .deps import get_auth

        auth = get_auth()
        if x_api_key:
            result = auth.verify_api_key(x_api_key)
            if result:
                user_id, _ = result
                org_id = auth.get_tenant_id(user_id)
        elif auth_header.startswith("Bearer "):
            token = auth_header[7:]
            result = auth.verify_api_key(token)
            if result:
                user_id, _ = result
                org_id = auth.get_tenant_id(user_id)
            else:
                clerk_claims = auth.verify_clerk_token(token)
                if clerk_claims:
                    org_id = (
                        clerk_claims.get("org_id")
                        or clerk_claims.get("organization_id")
                        or (
                            clerk_claims.get("o", {}).get("id")
                            if isinstance(clerk_claims.get("o"), dict)
                            else None
                        )
                    )

        proxy = ComplyGatewayProxy()
        target_path = f"/v1/{path}"

        # Detect streaming chat-completion requests.
        is_stream = False
        if request.method == "POST" and target_path == "/v1/chat/completions":
            try:
                payload = json.loads(body.decode("utf-8", errors="ignore"))
                is_stream = payload.get("stream", False) is True
            except Exception:
                is_stream = False

        try:
            if is_stream:
                async with proxy.stream(
                    body=body,
                    headers=headers,
                    org_id=org_id,
                    path=target_path,
                    method=request.method,
                ) as resp:
                    response_headers = map_response_headers(dict(resp.headers))
                    response_headers.pop("content-length", None)
                    response_headers.pop("transfer-encoding", None)

                    async def _stream_body():
                        async for chunk in resp.aiter_raw():
                            yield chunk

                    return StreamingResponse(
                        _stream_body(),
                        status_code=resp.status_code,
                        headers=response_headers,
                    )

            result = await proxy.forward(
                body=body,
                headers=headers,
                org_id=org_id,
                path=target_path,
                method=request.method,
            )
        except GatewayProxyError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        finally:
            await proxy.close()

        return Response(
            content=result["body"],
            status_code=result["status_code"],
            headers=result["headers"],
        )

    # Well-known discovery (evidence public key) — no prefix, per RFC 8615
    app.include_router(well_known_router)

    # Tenant retention settings (PRODUCT_SECURITY.md §4 gap #5)
    app.include_router(settings_router, prefix="/api/v1")

    # Programme tracker (Gap #5 — obligation lifecycle states)
    from .programme import router as programme_router

    app.include_router(programme_router, prefix="/api/v1")
    app.include_router(continuous_router, prefix="/api/v1")

    # Draft session bridge (Gap #2 — recipe ↔ agent unification)
    from .draft_sessions import router as draft_sessions_router

    app.include_router(draft_sessions_router, prefix="/api/v1")

    # Self-service GDPR Art. 17 / Art. 20 (per-user export + erase)
    from .me import router as me_router

    app.include_router(me_router, prefix="/api/v1")

    # Per-tenant organisation profile (drives Onboarding + recipe tailoring)
    from .org_profile import router as org_profile_router

    app.include_router(org_profile_router, prefix="/api/v1")

    # AI-enhanced onboarding (free-text → OrgProfile + adaptive next-question)
    from .onboarding import router as onboarding_router

    app.include_router(onboarding_router, prefix="/api/v1")

    # LLM strategy advisor (recommends hosted/local/byok per user)
    from .llm_strategy import router as llm_strategy_router

    app.include_router(llm_strategy_router, prefix="/api/v1")

    # Checkpoint resolution (human-in-the-loop for PEP tool gating)
    from .checkpoint_routes import router as checkpoint_router

    app.include_router(checkpoint_router, prefix="/api/v1")

    # Business impact assessment (AI-driven gap analysis)
    from .impact_routes import router as impact_router

    app.include_router(impact_router, prefix="/api/v1")

    # Free-text intent parser (natural language → safety policy)
    from .intent_routes import router as intent_router

    app.include_router(intent_router, prefix="/api/v1")

    # Safety Control Plane (tool policies, enforcement status, safety budget)
    from .safety import router as safety_router

    app.include_router(safety_router, prefix="/api/v1")

    # Phase 7 — Team RBAC and evidence sharing
    from .sharing import router as shares_router

    app.include_router(shares_router, prefix="/api/v1")
    # TODO: team_router module does not exist yet; re-enable once implemented.
    # app.include_router(team_router, prefix="/api/v1")

    # Gateway audit evidence endpoints
    from .gateway_audit_routes import router as gateway_audit_router

    app.include_router(gateway_audit_router, prefix="/api/v1")

    # Unified audit-log timeline
    from .audit_log import router as audit_log_router

    app.include_router(audit_log_router, prefix="/api/v1")

    # Generic HMAC-signed inbound webhook receiver (mirrors outbound signing)
    _CRP_COMPLY_WEBHOOK_TOLERANCE = int(
        os.environ.get("CRP_COMPLY_WEBHOOK_TOLERANCE_SECONDS", "300")
    )

    @app.post("/api/v1/webhooks/{source}")
    async def receive_webhook(
        source: str,
        request: Request,
        x_crpcomply_signature: str | None = Header(None),
    ) -> dict[str, Any]:
        secret = os.environ.get(f"CRP_COMPLY_WEBHOOK_SECRET_{source.upper()}") or os.environ.get(
            "CRP_COMPLY_WEBHOOK_SECRET", ""
        )
        if not secret:
            logger.warning("Webhook received for source '%s' but no secret configured", source)
            raise HTTPException(status_code=503, detail="Webhook source not configured")

        raw_body = await request.body()
        if not verify_signature(
            secret, raw_body, x_crpcomply_signature, tolerance_seconds=_CRP_COMPLY_WEBHOOK_TOLERANCE
        ):
            logger.warning("Invalid webhook signature for source '%s'", source)
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {"_raw": raw_body.decode("utf-8", errors="replace")}
        logger.info(
            "Webhook accepted for source '%s': event=%s", source, payload.get("event", "unknown")
        )

        # Persist Gateway audit streams as compliance evidence.
        if source == "gateway-audit" and _comply_pool is not None:
            try:
                from ..gateway_audit_store import persist_audit_events as _persist_audit_events

                events = payload.get("events", [])
                session_id = payload.get("session_id")
                tenant_id = payload.get("tenant_id")
                audit_secret = os.environ.get("CRP_GATEWAY_AUDIT_SECRET") or os.environ.get(
                    "CRP_GATEWAY_KEY", ""
                )
                hmac_secret = audit_secret.encode("utf-8") if audit_secret else None
                count = await _persist_audit_events(
                    _comply_pool, events, tenant_id, session_id, hmac_secret=hmac_secret
                )
                logger.info("Persisted %s Gateway audit events for session %s", count, session_id)
                return {"status": "ok", "source": source, "persisted": count}
            except Exception as exc:
                logger.warning("Failed to persist Gateway audit events: %s", exc)
                raise HTTPException(
                    status_code=500, detail="Failed to persist audit events"
                ) from exc

        return {"status": "ok", "source": source}

    frontend_dir = Path(
        os.environ.get(
            "CRP_COMPLY_FRONTEND_DIR",
            str(Path(__file__).parent.parent.parent.parent / "frontend" / "dist"),
        )
    )
    if frontend_dir.exists():
        # SPA fallback — the React app uses client-side routing for paths
        # like ``/app/programme`` and ``/app/evidence``. ``StaticFiles``
        # with ``html=True`` only serves ``index.html`` for the bare root,
        # so direct navigation or page refresh on a sub-route returned a
        # 404 (``{"detail":"Not Found"}``). The catch-all below resolves
        # the requested path against the build directory; if it's a real
        # file we serve it, otherwise we hand back ``index.html`` so the
        # router can rehydrate.
        #
        # NB: this module uses ``from __future__ import annotations`` so
        # parameter annotations are stored as strings. FastAPI resolves
        # them via ``get_type_hints()`` against the *module* globals,
        # which means any special types (e.g. ``Request``) must be
        # imported at module scope — if they're imported inside the
        # factory, FastAPI can't see them, falls through to dependency
        # resolution, and treats the parameter as a required *query*
        # parameter (“Field required” 422 on every refresh). We
        # sidestep the trap entirely by not declaring a Request param.
        from fastapi.responses import FileResponse

        index_file = frontend_dir / "index.html"

        # Mount hashed static assets FIRST so the catch-all below
        # never intercepts them. If the catch-all wins, a missing
        # hash returns ``{"detail": "Asset not found"}`` with
        # ``content-type: application/json`` — strict-MIME-checking
        # browsers then refuse the stylesheet ("Refused to apply
        # style ... application/json"). With the mount in front,
        # StaticFiles returns a real 404 and the browser only sees
        # the missing-asset error — not a MIME mismatch.
        assets_dir = frontend_dir / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="frontend-assets",
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa_fallback(full_path: str) -> Response:
            # Never shadow API routes — those are mounted earlier and would
            # match first, but guard explicitly in case order changes.
            if full_path.startswith(("api/", "v1/", ".well-known/")):
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not Found")
            # Defensive: if /assets mount missed (e.g. dist/assets
            # absent in dev), still 404 the request as plain text
            # so the browser doesn't get HTML for a CSS/JS path.
            if full_path.startswith("assets/"):
                return Response(
                    content="asset not found",
                    status_code=404,
                    media_type="text/plain",
                )
            candidate = (frontend_dir / full_path).resolve()
            try:
                candidate.relative_to(frontend_dir.resolve())
            except ValueError:
                # Path traversal attempt — fall through to index.
                return FileResponse(index_file)
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)

    return app
