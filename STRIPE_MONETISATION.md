# CRP Product Monetisation — Stripe Integration Plan

## Product 1: CRP Scribe

| | Free | Pro | Enterprise |
|---|---|---|---|
| **Price** | $0/mo | $39/mo | $299/mo |
| **Stripe Price ID** | — | `price_scribe_pro_monthly` | `price_scribe_enterprise_monthly` |
| Templates | 2 basic | All 5+ templates | All + custom |
| LLM Providers | 1 (OpenAI) | All 4 providers | All + private models |
| Generations/mo | 50 | 500 | Unlimited |
| Max doc length | 5,000 words | 50,000 words | Unlimited |
| Export formats | Markdown | MD, PDF, DOCX | All + API export |
| Version history | 7 days | 90 days | Unlimited |
| Priority support | — | Email | Dedicated Slack |
| Clerk auth | ✓ | ✓ | ✓ + SSO/SAML |

## Product 2: CRP Comply

| | Free | Pro | Enterprise | Cloud |
|---|---|---|---|---|
| **Price** | $0/mo | $149/mo | $699/mo | $1,999/mo |
| **Stripe Price ID** | — | `price_comply_pro_monthly` | `price_comply_enterprise_monthly` | `price_comply_cloud_monthly` |
| Frameworks | 2 (EU AI Act, GDPR) | All 7 frameworks | All + custom | All + custom |
| Proxy requests/mo | 100 | 10,000 | 100,000 | Unlimited |
| PII scanning | Basic (CRP PIIScanner) | Full 7-category | Full + custom patterns | Full + ML-enhanced |
| Injection detection | 21 patterns | 21 patterns + alerts | 21 + ML backends | Full CRP stack |
| Audit retention | 7 days | 90 days | 1 year | 7 years |
| GDPR Art. 30 records | ✓ | ✓ | ✓ | ✓ |
| Right to erasure | — | ✓ | ✓ | ✓ |
| Data classification | — | ✓ | ✓ | ✓ |
| Risk classification | — | — | ✓ (EU AI Act Art. 6) | ✓ |
| Chain verification | — | ✓ | ✓ | ✓ |
| Regulatory export | — | — | ✓ | ✓ + automated |
| DPIA generation | — | — | ✓ | ✓ |
| Human oversight | — | — | ✓ | ✓ |
| RBAC | — | — | ✓ | ✓ |
| Dedicated infra | — | — | — | ✓ |
| SLA | — | 99.5% | 99.9% | 99.95% |
| Support | Community | Email | Priority + Slack | Dedicated CSM |

---

## Stripe Integration Architecture

### 1. Products & Prices (create in Stripe Dashboard or API)

```
Stripe Products:
├── prod_crp_scribe        "CRP Scribe"
│   ├── price_scribe_pro_monthly         $39/mo  (recurring)
│   └── price_scribe_enterprise_monthly  $299/mo (recurring)
│
└── prod_crp_comply        "CRP Comply"
    ├── price_comply_pro_monthly          $149/mo  (recurring)
    ├── price_comply_enterprise_monthly   $699/mo  (recurring)
    └── price_comply_cloud_monthly        $1,999/mo (recurring)
```

### 2. Integration Flow

```
Customer clicks "Upgrade" in app
        │
        ▼
Frontend → POST /api/stripe/create-checkout-session
        │
        ▼
Backend creates Stripe Checkout Session
  - mode: "subscription"
  - line_items: [{ price: "price_xxx", quantity: 1 }]
  - success_url: "https://app.crprotocol.io/billing/success?session_id={CHECKOUT_SESSION_ID}"
  - cancel_url: "https://app.crprotocol.io/billing/cancel"
  - customer_email: from Clerk auth
  - metadata: { clerk_user_id, product }
        │
        ▼
Stripe redirects customer to hosted Checkout page
        │
        ▼
Customer pays → Stripe redirects to success_url
        │
        ▼
Stripe sends webhook: checkout.session.completed
        │
        ▼
POST /api/stripe/webhook
  - Verify signature (<YOUR_STRIPE_WEBHOOK_SECRET>)
  - Extract subscription ID + customer ID
  - Map Clerk user → Stripe customer
  - Update user tier in DB (free → pro/enterprise/cloud)
  - Provision features
```

### 3. Key Webhook Events to Handle

| Event | Action |
|---|---|
| `checkout.session.completed` | Activate subscription, upgrade tier |
| `invoice.paid` | Confirm renewal, extend access |
| `invoice.payment_failed` | Notify user, grace period (3 days) |
| `invoice.payment_action_required` | **(Wave 3)** Surface 3DS / SCA challenge — emits `billing_action_required` notification with `hosted_invoice_url` |
| `customer.subscription.updated` | Handle plan changes (up/downgrade) |
| `customer.subscription.deleted` | Downgrade to free tier |

> **Wave 3 additions also include:**
> - `Tier.STARTER` ($49/mo, 5K calls included) wired through enum,
>   `TIER_FEATURES`, `TIER_MONTHLY_QUOTA`, `OVERAGE_POLICY`, and the
>   billing checkout price-map (env: `STRIPE_COMPLY_STARTER_PRICE_ID`).
> - `GET /api/v1/billing/status` returning current tier, customer ID,
>   subscription ID, and ISO `current_period_end` (used by the frontend
>   plan badge).
> - **Opt-in metered overage billing** via `stripe.billing.meter_event`
>   gated on `STRIPE_METER_EVENT_NAME` (e.g. `comply_proxy_requests`).
>   See [USER_ACTIONS_REQUIRED.md §1.5](USER_ACTIONS_REQUIRED.md#15--quotas-seats-and-how-requests-are-counted).
>
> **Trials are not used.** The earlier draft of this doc mentioned
> `customer.subscription.trial_will_end`; that handler has been removed.

### 4. Backend Implementation (FastAPI)

```python
# Required packages:
# pip install stripe

# Environment variables:
# STRIPE_SECRET_KEY=<YOUR_STRIPE_SECRET_KEY>
# STRIPE_WEBHOOK_SECRET=<YOUR_STRIPE_WEBHOOK_SECRET>
# STRIPE_SCRIBE_PRO_PRICE_ID=<YOUR_STRIPE_PRICE_ID>
# STRIPE_SCRIBE_ENTERPRISE_PRICE_ID=<YOUR_STRIPE_PRICE_ID>
# STRIPE_SECRET_KEY=<YOUR_STRIPE_SECRET_KEY>
# STRIPE_WEBHOOK_SECRET=<YOUR_STRIPE_WEBHOOK_SECRET>
# STRIPE_SCRIBE_PRO_PRICE_ID=<YOUR_STRIPE_PRICE_ID>
# STRIPE_SCRIBE_ENTERPRISE_PRICE_ID=<YOUR_STRIPE_PRICE_ID>
# STRIPE_COMPLY_STARTER_PRICE_ID=<YOUR_STRIPE_PRICE_ID>     # NEW — $49 tier
# STRIPE_COMPLY_PRO_PRICE_ID=<YOUR_STRIPE_PRICE_ID>
# STRIPE_COMPLY_ENTERPRISE_PRICE_ID=<YOUR_STRIPE_PRICE_ID>
# (CLOUD tier is contact-sales — no public price ID needed)
# STRIPE_METER_EVENT_NAME=comply_proxy_requests        # required for overage
```

### 5. Stripe Dashboard Setup Checklist

- [ ] Create Stripe account (business: AutoCyber AI Pty Ltd, ABN: 22 697 087 166)
- [ ] Enable test mode
- [ ] Create products: "CRP Scribe", "CRP Comply"
- [ ] Create prices for each tier (recurring, monthly)
- [ ] Configure tax settings (Australian GST + international)
- [ ] Set up webhook endpoint: `https://comply.crprotocol.io/api/stripe/webhook`
- [ ] Set up webhook endpoint: `https://scribe.crprotocol.io/api/stripe/webhook`
- [ ] Subscribe to events: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`
- [ ] Configure customer portal for self-service billing management
- [ ] Install Stripe CLI for local testing: `stripe listen --forward-to localhost:8400/api/stripe/webhook`
- [ ] Switch to live mode when ready

### 6. Currency & Tax

- **Default currency**: AUD (Australian business)
- **Display currency**: USD (international SaaS standard)
- **Tax**: Stripe Tax handles GST (AU), VAT (EU), Sales Tax (US) automatically
- **Tax settings**: Enable Stripe Tax, set business address, register for taxes

### 7. Customer Portal

Enable Stripe's hosted Customer Portal so users can:
- View invoices
- Update payment method
- Switch plans (upgrade/downgrade)
- Cancel subscription
- Download receipts/tax invoices

Portal URL: `https://billing.stripe.com/p/login/...` (auto-provisioned)
