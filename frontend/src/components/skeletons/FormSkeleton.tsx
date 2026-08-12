import { Skeleton } from '@/design/primitives'

interface FormSkeletonProps {
  fields?: number
  className?: string
}

export function FormSkeleton({ fields = 4, className }: FormSkeletonProps) {
  return (
    <div
      className={`space-y-5 ${className ?? ''}`}
      role="status"
      aria-label="Loading form"
      aria-busy="true"
    >
      {Array.from({ length: fields }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-1/4 motion-reduce:animate-none" />
          <Skeleton className="h-10 w-full motion-reduce:animate-none" />
        </div>
      ))}
      <Skeleton className="h-10 w-32 motion-reduce:animate-none" />
      <span className="sr-only">Loading form…</span>
    </div>
  )
}
