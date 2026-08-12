import { renderHook, waitFor, act } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useOptimisticMutation } from '../mutations'

describe('useOptimisticMutation', () => {
  function wrapper(client: QueryClient) {
    return function Wrapper({ children }: { children: React.ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>
    }
  }

  it('optimistically removes an item and rolls back on error', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const key = ['items']
    client.setQueryData(key, [{ id: 'a' }, { id: 'b' }])

    const { result } = renderHook(
      () =>
        useOptimisticMutation<{ id: string }[], string, string>({
          mutationFn: async () => {
            await new Promise((resolve) => setTimeout(resolve, 50))
            throw new Error('boom')
          },
          queryKey: key,
          updateFn: (old, id) => (old ?? []).filter((item) => item.id !== id),
        }),
      { wrapper: wrapper(client) },
    )

    act(() => {
      result.current.mutate('a')
    })

    await waitFor(() => expect(client.getQueryData(key)).toEqual([{ id: 'b' }]))
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(client.getQueryData(key)).toEqual([{ id: 'a' }, { id: 'b' }])
  })

  it('optimistically prepends an item on success', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const key = ['items']
    client.setQueryData(key, [{ id: 'a' }])

    const { result } = renderHook(
      () =>
        useOptimisticMutation<{ id: string }[], { id: string }, { id: string }>({
          mutationFn: async (vars) => vars,
          queryKey: key,
          updateFn: (old, vars) => [vars, ...(old ?? [])],
        }),
      { wrapper: wrapper(client) },
    )

    act(() => {
      result.current.mutate({ id: 'b' })
    })

    await waitFor(() => expect(client.getQueryData(key)).toEqual([{ id: 'b' }, { id: 'a' }]))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })
})
