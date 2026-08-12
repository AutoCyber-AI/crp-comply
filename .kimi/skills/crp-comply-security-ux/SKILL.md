# CRP Comply Security UX Skill

Use this skill when implementing authentication, session management, passkey flows, trust badges, or any security-related UI in CRP Comply.

## Principle

Security is a satisfaction driver, not friction. Make security controls visible and understandable.

## Trust badges

Surface these badges in the app header, footer, landing page, and onboarding:

| Badge | Control it represents | When to show |
|---|---|---|
| "Passkey verified" | FIDO2/WebAuthn authentication | After successful passkey setup/verify |
| "HMAC-signed chain: intact" | Tamper-evident audit chain | On every evidence item and audit log |
| "0 bytes leave your network" | Local LLM inference | When local provider is selected |
| "AES-256 at rest" | Field-level encryption | Settings / storage panel |
| "TLS 1.3" | Transport security | Footer, public pages |
| SOC 2 / ISO 27001 / GDPR | Certifications (when obtained) | Near CTAs on landing page |

Badges must be factual. Do not claim certifications that do not exist.

## Passkey flows

- Passkey MFA is mandatory in production (kill-switch only in dev).
- Use Conditional UI for identifier-first login when the browser supports it.
- Progressive enrolment: prompt for passkey creation at account creation or recovery, not as a forced cutover.
- Cross-device fallback: support hybrid transport (QR + BLE).
- Success target: >95% authentication success rate, <10 s median sign-in time.

## Session architecture

Target state:

- **Web app:** Redis-backed sessions in `HttpOnly`, `Secure`, `SameSite=Strict` cookies.
- **CLI / SDK:** short-lived signed JWT (RS256 for distributed services, HS256 for internal only).
- **Passkey MFA:** server-side `credential_id_hash` + `sign_count` validation + atomic session rotation.

Migration path from current sessionStorage MFA token:

1. Backend adds Redis session + cookie endpoints.
2. Frontend reads cookie; sessionStorage token becomes legacy fallback.
3. After 30 days, remove fallback.

## Adaptive / step-up authentication

Sensitive actions requiring step-up:

- Billing changes
- API key creation / deletion
- Evidence export / evidence pack signing
- Organisation ownership transfer
- Bulk user invitation

Risk signals:

- New device / browser fingerprint
- Unusual geolocation
- No passkey verification in the current session
- High-value action

Step-up UI: modal re-using passkey verification; preserve workflow context.

## Error & recovery

- Never blame the user for auth failures.
- Provide a clear recovery path: "Try again", "Use a different passkey", "Contact support".
- Log security events to the tamper-evident audit chain.

## Testing

- Test passkey flows with `@simplewebauthn/browser` mocks.
- Verify session revocation invalidates cookies immediately.
- Confirm no tokens are stored in `localStorage` or `sessionStorage` after Phase 5.
