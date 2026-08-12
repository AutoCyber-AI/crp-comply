import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import Vault from '../Vault'
import { listReports, listEvidencePacks, getEvidencePack } from '@/lib/api'
import { useAuth } from '@clerk/react'
import { ToastProvider } from '@/components/toast/ToastProvider'

vi.mock('@/lib/api', () => ({
  listReports: vi.fn(),
  listEvidencePacks: vi.fn(),
  getEvidencePack: vi.fn(),
  getReport: vi.fn(),
  downloadReportMarkdownUrl: vi.fn((id: string) => `/api/v1/reports/${id}/markdown`),
  downloadEvidencePackUrl: vi.fn((id: string) => `/api/v1/evidence-packs/${id}/download`),
}))

vi.mock('@clerk/react', () => ({
  useAuth: vi.fn(),
}))

const pack = {
  pack_id: 'pack_123',
  system_name: 'Test system pack',
  category: 'high-risk',
  tier: 'pro',
  created_at: new Date().toISOString(),
  file_count: 2,
  zip_bytes: 1024,
  sources: ['regulation', 'artefact'],
}

const manifest = {
  pack_id: 'pack_123',
  user_id: 'user_123',
  system_name: 'Test system pack',
  category: 'high-risk',
  tier: 'pro',
  created_at: new Date().toISOString(),
  crp_comply_version: '1.0.0',
  files: [
    {
      name: 'report.md',
      kind: 'markdown',
      size_bytes: 1200,
      sha256: 'a'.repeat(64),
      hmac_sha256: null,
    },
    {
      name: 'metadata.json',
      kind: 'metadata',
      size_bytes: 450,
      sha256: 'b'.repeat(64),
      hmac_sha256: null,
    },
  ],
  signature: {
    algorithm: 'ed25519',
    signature_b64: 'sigsignaturebase64==',
    public_key_b64: 'pubkeybase64==',
    key_fingerprint: 'a1b2c3d4',
    signed_at: new Date().toISOString(),
  },
}

function Wrapper({ initialEntries = ['/app/vault'] }: { initialEntries?: string[] } = {}) {
  return (
    <MemoryRouter initialEntries={initialEntries}>
      <ToastProvider>
        <Vault />
      </ToastProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({ isLoaded: true, isSignedIn: true } as ReturnType<typeof useAuth>)
  vi.mocked(listReports).mockResolvedValue({ reports: [], counts: {}, total: 0, total_bytes: 0 })
  vi.mocked(listEvidencePacks).mockResolvedValue({ packs: [pack] })
  vi.mocked(getEvidencePack).mockResolvedValue(manifest)
})

describe('Vault pack detail', () => {
  it('renders provenance pills on the evidence pack card', async () => {
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByText('Test system pack')).toBeInTheDocument()
    })
    expect(screen.getByText('Regulation')).toBeInTheDocument()
    expect(screen.getByText('Artefact')).toBeInTheDocument()
  })

  it('opens pack detail from card click and renders signature info', async () => {
    render(<Wrapper />)
    await waitFor(() => {
      expect(screen.getByText('Test system pack')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByText('Test system pack'))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Signature/i })).toBeInTheDocument()
    })
    expect(screen.getByText(/ed25519/i)).toBeInTheDocument()
    expect(screen.getByText(/a1b2c3d4/)).toBeInTheDocument()
    expect(screen.getByText(/pubkeybase64==/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Verify signature/i })).toBeInTheDocument()
    expect(screen.getByTitle(manifest.files[0].sha256)).toBeInTheDocument()
  })
})
