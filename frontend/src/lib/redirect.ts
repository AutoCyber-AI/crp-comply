/**
 * Validate and sanitize a post-auth redirect URL.
 *
 * Only same-origin relative paths are allowed. This prevents open-redirect
 * attacks where a malicious actor crafts a link like
 * `/sign-in?redirect_url=https://evil.com`.
 */
export function validateRedirectUrl(raw: string | null | undefined, fallback = '/app'): string {
  if (!raw) return fallback
  try {
    // Reject absolute URLs and protocol-relative URLs.
    if (/^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith('//')) {
      return fallback
    }
    // Only permit root-relative paths.
    if (!raw.startsWith('/')) {
      return fallback
    }
    // Reject URLs that contain CRLF or attempt to inject headers.
    if (/[\r\n]/.test(raw)) {
      return fallback
    }
    return raw
  } catch {
    return fallback
  }
}
