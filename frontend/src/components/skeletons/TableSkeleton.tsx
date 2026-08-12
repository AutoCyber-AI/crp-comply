import { Skeleton } from '@/design/primitives'

interface TableSkeletonProps {
  rows?: number
  columns?: number
  className?: string
}

export function TableSkeleton({ rows = 6, columns = 4, className }: TableSkeletonProps) {
  return (
    <div
      className={className}
      role="status"
      aria-label="Loading table"
      aria-busy="true"
    >
      <div className="border border-hairline rounded-lg overflow-hidden">
        {/* Header */}
        <div className="grid gap-3 p-3 bg-surface-2" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
          {Array.from({ length: columns }).map((_, i) => (
            <Skeleton key={`h-${i}`} className="h-4 w-3/4 motion-reduce:animate-none" />
          ))}
        </div>
        {/* Rows */}
        <div className="divide-y divide-hairline">
          {Array.from({ length: rows }).map((_, r) => (
            <div
              key={`r-${r}`}
              className="grid gap-3 p-3 items-center"
              style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
            >
              {Array.from({ length: columns }).map((__, c) => (
                <Skeleton
                  key={`c-${c}`}
                  className="h-3 w-full motion-reduce:animate-none"
                  style={{ opacity: 1 - (r % 3) * 0.15 }}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      <span className="sr-only">Loading table data…</span>
    </div>
  )
}
