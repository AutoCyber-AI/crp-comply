# CRP Comply Dead Code Cleanup Plan

## CRITICAL — Remove or Wire Up

### 1. `src/crp_comply/gateway_proxy.py` — DEAD CODE
**Status:** Module exists but is **never imported** in `api/app.py`. The bespoke proxy at `/v1` still serves all traffic.

**Decision:** Intentionally deferred (SPEC-042 Gateway swap). Keep module but add docstring noting it is not mounted. Remove when Gateway swap is implemented.

**Action:**
```python
# Add to top of gateway_proxy.py:
"""DEAD CODE — SPEC-042 Gateway swap is intentionally deferred.

This module is not imported by api/app.py. The live path uses
proxy/routes.py (bespoke compliance proxy). Do not delete until
Gateway swap is implemented and tested.
"""
```

### 2. `src/crp_comply/billing/webhook.py` — DEAD CODE
**Status:** Canonical webhook handler with Clerk sync, but **never mounted**. Live handler is inline in `api/billing.py`.

**Decision:** The canonical handler has better Clerk sync logic. We should unify.

**Action:**
- Copy Clerk sync logic from `billing/webhook.py` into `api/billing.py`
- Delete `billing/webhook.py` and remove from `billing/__init__.py`

### 3. `src/crp_comply/header_mapping.py` — UNCALLED
**Status:** `strip_crp_headers_before_provider()` exists but is **never called** in the live proxy path.

**Decision:** Axiom 4 compliance requires this. Must integrate into proxy.

**Action:**
- Import and call `strip_crp_headers_before_provider()` in `proxy/routes.py` before forwarding
- If proxy is being replaced by Gateway, add call in `gateway_proxy.py` instead

---

## HIGH — Refactor

### 4. Direct `auth._users` access
**Files:** `api/billing.py` (6+ locations), `api/routes.py:566`

**Action:** Add methods to `AuthManager`:
```python
def set_stripe_ids(self, user_id: str, customer_id: str, subscription_id: str) -> None:
    if user_id in self._users:
        self._users[user_id]["stripe_customer_id"] = customer_id
        self._users[user_id]["stripe_subscription_id"] = subscription_id
        self._save_users()

def get_user_data(self, user_id: str) -> dict:
    return self._users.get(user_id, {})
```

### 5. `api/billing.py` legacy typo env var
**Line 54:** `STRIPE_COMPLY_PROFESISIONAL_PRICE_ID`

**Action:** Remove after confirming no prod deployment uses it.

### 6. `core.py` ancient fallback version
**Lines 847-852:** Returns `"2.0.0"` on exception.

**Action:** Return `"unknown"` or read from `crp_comply.__version__`.

---

## MEDIUM — Polish

### 7. `agent/llm.py` `_autodetect()` raises RuntimeError
**Action:** Return `None` and let caller return 422/503 with clear message.

### 8. CORS overly permissive
**File:** `api/app.py:378-389`

**Action:** Restrict to specific methods/headers:
```python
allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
allow_headers=["Authorization", "Content-Type", "X-Api-Key", "X-Request-ID"],
```

---

## Test Coverage Gaps

Add tests for:
- `test_billing_webhook.py` — mock Stripe events, verify idempotency
- `test_gateway_proxy.py` — mock upstream with `respx`
- `test_github_routes.py` — HMAC verification
- `test_no_code.py` — config generation without CRP v4 installed
