import { Skeleton } from '@/design/primitives'

interface ContentSkeletonProps {
  lines?: number
  className?: string
}

export function ContentSkeleton({ lines = 8, className }: ContentSkeletonProps) {
  return (
    <div
      className={className}
      role="status"
      aria-label="Loading content"
      aria-busy="true"
    >
      <Skeleton className="h-7 w-2/3 mb-6 motion-reduce:animate-none" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="h-3 mb-3 motion-reduce:animate-none"
          style={{ width: `${85 + (i % 3) * 5}%`, opacity: 1 - (i % 4) * 0.1 }}
        />
      ))}
      <span className="sr-only">Loading content…</span>
    </div>
  )
}
