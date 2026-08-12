import { useCallback, useState } from 'react'

interface UseStepUpOptions {
  actionName: string
}

export function useStepUp({ actionName }: UseStepUpOptions) {
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null)
  const [open, setOpen] = useState(false)

  const requireStepUp = useCallback((action: () => void) => {
    setPendingAction(() => action)
    setOpen(true)
  }, [])

  const close = useCallback(() => {
    setOpen(false)
    setPendingAction(null)
  }, [])

  const onVerified = useCallback(() => {
    setOpen(false)
    pendingAction?.()
    setPendingAction(null)
  }, [pendingAction])

  return {
    open,
    actionName,
    requireStepUp,
    close,
    onVerified,
  }
}
