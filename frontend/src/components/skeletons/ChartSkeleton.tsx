import { Skeleton } from '@/design/primitives'

interface ChartSkeletonProps {
  className?: string
}

export function ChartSkeleton({ className }: ChartSkeletonProps) {
  return (
    <div
      className={`border border-hairline rounded-xl p-5 bg-surface ${className ?? ''}`}
      role="status"
      aria-label="Loading chart"
      aria-busy="true"
    >
      <Skeleton className="h-5 w-1/3 mb-4 motion-reduce:animate-none" />
      <div className="relative h-48 w-full">
        <Skeleton className="absolute inset-0 motion-reduce:animate-none" />
        {/* Bar placeholders */}
        <div className="absolute inset-0 flex items-end justify-around px-4 pb-4 gap-3">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton
              key={i}
              className="w-full rounded-t motion-reduce:animate-none"
              style={{ height: `${20 + (i % 5) * 15}%`, opacity: 0.7 + (i % 3) * 0.1 }}
            />
          ))}
        </div>
      </div>
      <span className="sr-only">Loading chart data…</span>
    </div>
  )
}
