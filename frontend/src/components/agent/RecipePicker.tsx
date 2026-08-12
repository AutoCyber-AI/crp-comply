import { useMemo, useState, useEffect, useRef } from 'react'
import { ChevronDown } from 'lucide-react'
import clsx from 'clsx'
import type { RecipeSummary } from '../../lib/api'
import { Skeleton } from '../../design/primitives'

export interface RecipePickerProps {
  recipes: RecipeSummary[] | null
  value: string
  onChange: (id: string) => void
}

export function RecipePicker({ recipes, value, onChange }: RecipePickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const filtered = useMemo(() => {
    if (!recipes) return []
    const q = query.trim().toLowerCase()
    if (!q) return recipes
    return recipes.filter(
      (r) =>
        r.title.toLowerCase().includes(q)
        || r.regulation.toLowerCase().includes(q)
        || r.recipe_id.toLowerCase().includes(q),
    )
  }, [recipes, query])

  const current = recipes?.find((r) => r.recipe_id === value)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        className="btn-outline min-w-[280px] justify-between"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Choose a recipe"
      >
        <span className="truncate">
          {current ? (
            <>
              <span className="font-mono text-xs text-ink-3 mr-2">{current.regulation}</span>
              {current.title}
            </>
          ) : (
            'Choose a recipe…'
          )}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" />
      </button>
      {open && (
        <div
          role="listbox"
          aria-label="Recipes"
          className="absolute left-0 top-full mt-2 w-[420px] max-w-[90vw] bg-surface border border-hairline shadow-crp-lg rounded-lg z-50 overflow-hidden animate-slide-up"
        >
          <div className="p-2 border-b border-hairline">
            <input
              autoFocus
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${recipes?.length ?? 0} recipes…`}
              className="input h-8 text-sm"
              aria-label="Search recipes"
            />
          </div>
          <ul className="max-h-[50vh] overflow-y-auto">
            {recipes === null && (
              <li className="p-4"><Skeleton className="h-10" /></li>
            )}
            {filtered.map((r) => (
              <li key={r.recipe_id} role="option" aria-selected={r.recipe_id === value}>
                <button
                  type="button"
                  className={clsx(
                    'w-full text-left px-3 py-2 hover:bg-primary-muted transition-colors duration-crp',
                    r.recipe_id === value && 'bg-primary-muted',
                  )}
                  onClick={() => { onChange(r.recipe_id); setOpen(false); setQuery('') }}
                >
                  <div className="text-xs font-mono text-ink-3">{r.regulation}</div>
                  <div className="text-sm font-medium truncate">{r.title}</div>
                </button>
              </li>
            ))}
            {filtered.length === 0 && recipes !== null && (
              <li className="px-3 py-6 text-center text-sm text-ink-3">No recipes match.</li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
