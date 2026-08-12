import { useState, useCallback } from 'react'
import { Terminal, Check } from 'lucide-react'
import { copyToClipboard } from '../lib/clipboard'
import { Tooltip } from '../design/primitives'

interface CliCopyButtonProps {
  command: string
  label?: string
  className?: string
  size?: 'sm' | 'md'
}

export function CliCopyButton({
  command,
  label,
  className,
  size = 'sm',
}: CliCopyButtonProps) {
  const [copied, setCopied] = useState(false)

  const handleClick = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation()
      const ok = await copyToClipboard(command)
      if (ok) {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1500)
      }
    },
    [command],
  )

  const iconSize = size === 'sm' ? 'h-3 w-3' : 'h-4 w-4'
  const buttonClass =
    size === 'sm'
      ? 'p-1.5 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 transition-colors'
      : 'inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-md border border-hairline text-ink-2 hover:text-ink hover:bg-surface-2 transition-colors'

  return (
    <Tooltip label={copied ? 'Copied!' : label || 'Copy CLI command'}>
      <button
        type="button"
        onClick={handleClick}
        className={`${buttonClass} ${className ?? ''}`}
        aria-label={`Copy CLI command: ${command}`}
      >
        {copied ? <Check className={`${iconSize} text-success`} /> : <Terminal className={iconSize} />}
        {size !== 'sm' && <span>CLI</span>}
      </button>
    </Tooltip>
  )
}
