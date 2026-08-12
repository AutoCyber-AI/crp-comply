/**
 * ShareButton — one-click evidence sharing dialog.
 *
 * Creates an expiring share link for a report or evidence pack, copies the
 * public URL to the clipboard, and lists existing shares for the resource.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Share2, X, Link2, Loader2, Trash2, Check } from 'lucide-react'
import { Button } from '../design/primitives'
import { useToast } from './toast/ToastProvider'
import { useFocusTrap } from '../hooks/useFocusTrap'
import {
  createShare,
  listShares,
  revokeShare,
  type ShareRecord,
  type CreateShareRequest,
} from '../lib/api'
import { copyToClipboard } from '../lib/clipboard'

interface ShareButtonProps {
  resourceType: 'report' | 'pack'
  resourceId: string
  resourceName?: string
  variant?: 'primary' | 'outline' | 'ghost'
  size?: 'sm' | 'md'
  disabled?: boolean
}

function sharePublicUrl(shareId: string): string {
  return `${window.location.origin}/api/v1/shares/${shareId}/public`
}

export function ShareButton({
  resourceType,
  resourceId,
  resourceName,
  variant = 'outline',
  size = 'sm',
  disabled,
}: ShareButtonProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        variant={variant}
        size={size}
        iconLeft={<Share2 className="h-3.5 w-3.5" />}
        onClick={() => setOpen(true)}
        disabled={disabled}
      >
        Share
      </Button>
      {open && (
        <ShareDialog
          resourceType={resourceType}
          resourceId={resourceId}
          resourceName={resourceName}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}

function ShareDialog({
  resourceType,
  resourceId,
  resourceName,
  onClose,
}: Omit<ShareButtonProps, 'variant' | 'size'> & { onClose: () => void }) {
  const toast = useToast()
  const ref = useFocusTrap<HTMLDivElement>({ active: true, onEscape: onClose })
  const [loading, setLoading] = useState(false)
  const [shares, setShares] = useState<ShareRecord[]>([])
  const [fetching, setFetching] = useState(true)
  const [recipientEmail, setRecipientEmail] = useState('')
  const [expiresInDays, setExpiresInDays] = useState(7)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listShares()
      .then((res) => {
        if (cancelled) return
        setShares(
          res.shares.filter(
            (s) => s.resource_type === resourceType && s.resource_id === resourceId,
          ),
        )
      })
      .catch((err) => {
        if (!cancelled) {
          toast.error('Could not load shares', err instanceof Error ? err.message : 'Unknown error')
        }
      })
      .finally(() => {
        if (!cancelled) setFetching(false)
      })
    return () => {
      cancelled = true
    }
  }, [resourceType, resourceId, toast])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [])

  const handleCreate = async () => {
    setLoading(true)
    try {
      const body: CreateShareRequest = {
        [`${resourceType === 'report' ? 'report_id' : 'pack_id'}`]: resourceId,
        recipient_email: recipientEmail.trim() || undefined,
        expires_in_days: expiresInDays,
      }
      const share = await createShare(body)
      setShares((prev) => [share, ...prev])
      const url = sharePublicUrl(share.share_id)
      const ok = await copyToClipboard(url)
      if (ok) {
        setCopiedId(share.share_id)
        window.setTimeout(() => setCopiedId((id) => (id === share.share_id ? null : id)), 2000)
        toast.success('Share link copied', url)
      } else {
        toast.success('Share link created', url)
      }
    } catch (err) {
      toast.error('Share failed', err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const handleRevoke = async (shareId: string) => {
    try {
      await revokeShare(shareId)
      setShares((prev) => prev.filter((s) => s.share_id !== shareId))
      toast.success('Share revoked')
    } catch (err) {
      toast.error('Could not revoke share', err instanceof Error ? err.message : 'Unknown error')
    }
  }

  const handleCopy = async (shareId: string) => {
    const url = sharePublicUrl(shareId)
    const ok = await copyToClipboard(url)
    if (ok) {
      setCopiedId(shareId)
      window.setTimeout(() => setCopiedId((id) => (id === shareId ? null : id)), 2000)
      toast.success('Link copied')
    } else {
      toast.error('Copy failed')
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-title"
    >
      <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div
        ref={ref}
        className="relative w-full max-w-lg rounded-xl border border-hairline bg-surface shadow-crp-lg p-6 animate-scale-in"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-primary/10 grid place-items-center">
              <Share2 className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h2 id="share-title" className="text-display text-lg font-bold text-ink">
                Share {resourceType === 'report' ? 'report' : 'evidence pack'}
              </h2>
              {resourceName && <p className="text-xs text-ink-3 truncate max-w-[16rem]">{resourceName}</p>}
            </div>
          </div>
          <button type="button" onClick={onClose} className="text-ink-4 hover:text-ink" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="share-recipient" className="block text-sm font-medium text-ink mb-1">
              Recipient email (optional)
            </label>
            <input
              id="share-recipient"
              type="email"
              value={recipientEmail}
              onChange={(e) => setRecipientEmail(e.target.value)}
              placeholder="colleague@example.com"
              className="input w-full"
            />
          </div>
          <div>
            <label htmlFor="share-expiry" className="block text-sm font-medium text-ink mb-1">
              Link expires in
            </label>
            <select
              id="share-expiry"
              value={expiresInDays}
              onChange={(e) => setExpiresInDays(Number(e.target.value))}
              className="select w-full"
            >
              <option value={1}>1 day</option>
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </div>

          <Button
            variant="primary"
            className="w-full"
            onClick={handleCreate}
            loading={loading}
            disabled={loading}
            iconLeft={loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
          >
            Create share link
          </Button>
        </div>

        <div className="mt-6">
          <h3 className="text-xs font-medium uppercase tracking-wider text-ink-3 mb-3">
            Existing shares
          </h3>
          {fetching ? (
            <div className="text-sm text-ink-3 animate-pulse">Loading…</div>
          ) : shares.length === 0 ? (
            <p className="text-sm text-ink-3">No active share links for this item.</p>
          ) : (
            <ul className="space-y-2 max-h-48 overflow-y-auto">
              {shares.map((s) => (
                <li
                  key={s.share_id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface-2 px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-xs font-mono truncate">{s.share_id.slice(0, 8)}…</div>
                    <div className="text-xs text-ink-3">
                      Expires {new Date(s.expires_at).toLocaleDateString()}
                      {s.recipient_email && <> · {s.recipient_email}</>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => handleCopy(s.share_id)}
                      className="p-1.5 rounded-md text-ink-3 hover:text-ink hover:bg-surface"
                      aria-label="Copy share link"
                      title="Copy share link"
                    >
                      {copiedId === s.share_id ? (
                        <Check className="h-3.5 w-3.5 text-emerald-600" />
                      ) : (
                        <Link2 className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRevoke(s.share_id)}
                      className="p-1.5 rounded-md text-ink-3 hover:text-danger hover:bg-danger/10"
                      aria-label="Revoke share"
                      title="Revoke share"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
