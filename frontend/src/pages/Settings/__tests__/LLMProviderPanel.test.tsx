import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LLMProviderPanel } from '../LLMProviderPanel'
import * as api from '@/lib/api'
import { useAuth } from '@clerk/react'
import { ToastProvider } from '@/components/toast/ToastProvider'

vi.mock('@clerk/react', () => ({
  useAuth: vi.fn(() => ({
    getToken: vi.fn(() => Promise.resolve('test-token')),
    isLoaded: true,
    isSignedIn: true,
  })),
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    getProviderStatus: vi.fn(),
    testProvider: vi.fn(),
    getLLMContext: vi.fn(),
    configureProvider: vi.fn(),
    diagnoseProvider: vi.fn(),
    removeProvider: vi.fn(),
    getWorkerStatus: vi.fn(),
  }
})

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    )
  }
}

const localStatus = {
  configured: true,
  provider: 'lmstudio' as const,
  base_url: 'http://localhost:1234/v1',
  model: 'local-model',
  configured_at: new Date().toISOString(),
  source: 'user' as const,
  dispatch_mode: null as string | null,
}

const commercialStatus = {
  configured: true,
  provider: 'openai' as const,
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-4o-mini',
  configured_at: new Date().toISOString(),
  source: 'user' as const,
  dispatch_mode: null as string | null,
}

describe('LLMProviderPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      getToken: vi.fn(() => Promise.resolve('test-token')),
      isLoaded: true,
      isSignedIn: true,
    } as unknown as ReturnType<typeof useAuth>)
    vi.mocked(api.getProviderStatus).mockResolvedValue({
      configured: false,
      provider: null,
      base_url: null,
      model: null,
      configured_at: null,
      source: 'none' as const,
      dispatch_mode: null,
    })
    vi.mocked(api.testProvider).mockResolvedValue({
      success: true,
      provider: 'openai',
      base_url: 'https://api.openai.com/v1',
      models: ['gpt-4o-mini'],
      latency_ms: 120,
      error: null,
    })
    vi.mocked(api.getLLMContext).mockResolvedValue({
      provider: 'openai',
      model: 'gpt-4o-mini',
      context_length: 128000,
    })
    vi.mocked(api.configureProvider).mockResolvedValue({
      configured: true,
      provider: 'openai',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
      configured_at: new Date().toISOString(),
    })
    vi.mocked(api.diagnoseProvider).mockResolvedValue({
      source: 'none' as const,
      provider: null,
      base_url: null,
      model: null,
      env_vars_seen: {},
    })
    vi.mocked(api.removeProvider).mockResolvedValue({ removed: true })
    vi.mocked(api.getWorkerStatus).mockResolvedValue({
      attached: false,
      user_id_hash: 'mock',
    })
  })

  it('renders the local-first CTA', async () => {
    render(<LLMProviderPanel />, { wrapper: createWrapper() })
    expect(await screen.findByText(/Keep your data on your network/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Detect LM Studio/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Detect Ollama/i })).toBeInTheDocument()
  })

  it('shows privacy badge for local providers', async () => {
    vi.mocked(api.getProviderStatus).mockResolvedValue(localStatus)
    render(<LLMProviderPanel />, { wrapper: createWrapper() })
    expect(await screen.findByText(/0 bytes leave your network/i)).toBeInTheDocument()
  })

  it('does not show privacy badge for commercial providers', async () => {
    vi.mocked(api.getProviderStatus).mockResolvedValue(commercialStatus)
    render(<LLMProviderPanel />, { wrapper: createWrapper() })
    await waitFor(() => {
      expect(screen.queryByText(/0 bytes leave your network/i)).not.toBeInTheDocument()
    })
  })

  it('displays model and context length after a successful test', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getProviderStatus).mockResolvedValue(commercialStatus)
    vi.mocked(api.getLLMContext).mockResolvedValue({
      provider: 'openai',
      model: 'gpt-4o-mini',
      context_length: 128000,
    })

    render(<LLMProviderPanel />, { wrapper: createWrapper() })

    const testButton = await screen.findByRole('button', { name: /Test connection/i })
    await user.click(testButton)

    await waitFor(() => {
      expect(api.testProvider).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(api.getLLMContext).toHaveBeenCalledTimes(1)
    })
    expect(await screen.findByText(/Model context/i)).toBeInTheDocument()
    expect(await screen.findByText(/128,000 tokens/i)).toBeInTheDocument()
  })

  it('chains detect LM Studio through configure, test, and context lookup', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getProviderStatus).mockResolvedValue({
      configured: false,
      provider: null,
      base_url: null,
      model: null,
      configured_at: null,
      source: 'none' as const,
      dispatch_mode: null,
    })
    vi.mocked(api.configureProvider).mockResolvedValue({
      configured: true,
      provider: 'lmstudio',
      base_url: 'http://localhost:1234/v1',
      model: 'local-model',
      configured_at: new Date().toISOString(),
    })
    vi.mocked(api.testProvider).mockResolvedValue({
      success: true,
      provider: 'lmstudio',
      base_url: 'http://localhost:1234/v1',
      models: ['local-model'],
      latency_ms: 45,
      error: null,
    })
    vi.mocked(api.getLLMContext).mockResolvedValue({
      provider: 'lmstudio',
      model: 'local-model',
      context_length: 32768,
    })

    render(<LLMProviderPanel />, { wrapper: createWrapper() })

    await user.click(screen.getByRole('button', { name: /Detect LM Studio/i }))

    await waitFor(() => {
      expect(api.configureProvider).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: 'lmstudio',
          base_url: 'http://localhost:1234/v1',
        }),
        expect.anything(),
      )
    })
    await waitFor(() => {
      expect(api.testProvider).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(api.getLLMContext).toHaveBeenCalledTimes(1)
    })
    expect(await screen.findByText(/32,768 tokens/i)).toBeInTheDocument()
  })
})
