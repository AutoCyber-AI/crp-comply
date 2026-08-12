import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'

export interface OptimisticMutationOptions<TData, TVariables, TResult, TContext> {
  mutationFn: (variables: TVariables) => Promise<TResult>
  queryKey: QueryKey
  updateFn: (oldData: TData | undefined, variables: TVariables) => TData
  onSuccess?: (data: TResult, variables: TVariables, context: TContext | undefined) => void | Promise<unknown>
  onError?: (error: Error, variables: TVariables, context: TContext | undefined) => void
}

/**
 * Wrapper around TanStack Query's useMutation that performs an optimistic
 * update on a single query cache and automatically rolls back on error.
 *
 * The update function must be pure and return the new cached data given the
 * previous data and the mutation variables. The mutation function's return
 * type does not have to match the cache data shape.
 */
export function useOptimisticMutation<TData, TVariables = void, TResult = TData>(
  options: OptimisticMutationOptions<TData, TVariables, TResult, unknown>,
) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: options.mutationFn,
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: options.queryKey })
      const previousData = queryClient.getQueryData<TData>(options.queryKey)
      queryClient.setQueryData<TData>(options.queryKey, (old) =>
        options.updateFn(old, variables),
      )
      return { previousData }
    },
    onError: (error, variables, context) => {
      if (context && 'previousData' in context) {
        queryClient.setQueryData(options.queryKey, context.previousData)
      }
      options.onError?.(error, variables, context)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: options.queryKey })
    },
    onSuccess: options.onSuccess,
  })
}
