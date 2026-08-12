import { Skeleton } from '@/design/primitives'

interface CardSkeletonProps {
  count?: number
  className?: string
}

export function CardSkeleton({ count = 4, className }: CardSkeletonProps) {
  return (
    <div
      className={`grid gap-4 sm:grid-cols-2 lg:grid-cols-${Math.min(count, 4)} ${className ?? ''}`}
      role="status"
      aria-label="Loading cards"
      aria-busy="true"
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="border border-hairline rounded-xl p-5 space-y-4 bg-surface"
        >
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-full motion-reduce:animate-none" />
            <Skeleton className="h-4 w-1/2 motion-reduce:animate-none" />
          </div>
          <Skeleton className="h-3 w-full motion-reduce:animate-none" />
          <Skeleton className="h-3 w-5/6 motion-reduce:animate-none" />
          <div className="flex gap-2 pt-2">
            <Skeleton className="h-6 w-16 rounded-full motion-reduce:animate-none" />
            <Skeleton className="h-6 w-16 rounded-full motion-reduce:animate-none" />
          </div>
        </div>
      ))}
      <span className="sr-only">Loading cards…</span>
    </div>
  )
}
