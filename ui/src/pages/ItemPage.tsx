// Item / Action page (#/items/:path). One component for both: the breadcrumb is
// the only difference (root -> "#123"; action -> "#123 / #123.1 / ..." each a
// link). Children render collapsed; a chevron lazy-loads the next level via the
// same /api/items/:path endpoint (one query per expanded child).
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronRight, ChevronDown } from 'lucide-react'
import { useItem, type ItemChild } from '@/hooks/useItems'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'

function Breadcrumb({ path }: { path: string }) {
  const segs = path.split('.')
  return (
    <nav data-testid="breadcrumb" className="flex flex-wrap items-center gap-1 text-sm">
      {segs.map((_, i) => {
        const p = segs.slice(0, i + 1).join('.')
        const last = i === segs.length - 1
        return (
          <span key={p} className="flex items-center gap-1">
            {i > 0 && <span className="text-muted-foreground">/</span>}
            {last ? (
              <span className="font-mono font-semibold">#{p}</span>
            ) : (
              <Link to={`/items/${p}`} className="font-mono text-primary hover:underline">
                #{p}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}

function ChildRow({ child }: { child: ItemChild }) {
  const [open, setOpen] = useState(false)
  const sub = useItem(open ? child.path : '')
  return (
    <div className="rounded border border-border bg-card">
      <div className="flex items-center gap-2 p-2">
        {child.has_children ? (
          <button
            data-testid={`expand-${child.path}`}
            aria-label={`Expand ${child.path}`}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        ) : (
          <span className="inline-block size-4" />
        )}
        <Link to={`/items/${child.path}`} className="font-mono text-xs text-primary hover:underline">
          #{child.path}
        </Link>
        <span className="min-w-0 flex-1 truncate text-sm">{child.summary}</span>
        <Badge variant="outline">{child.priority}</Badge>
        <Badge variant="secondary">{child.status}</Badge>
      </div>
      {open && (
        <div className="ml-6 space-y-1 border-l border-border pl-2 pb-2">
          {sub.isPending && <Skeleton className="h-6 w-full" />}
          {sub.data?.children.map((c) => <ChildRow key={c.path} child={c} />)}
        </div>
      )}
    </div>
  )
}

export function ItemPage() {
  const params = useParams()
  const path = params['*'] ?? ''
  const q = useItem(path)

  if (q.isPending) {
    return (
      <div data-testid="item-loading" className="space-y-3 p-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (q.isError) {
    const err = q.error as ApiError
    return (
      <div role="alert" className="p-6 text-destructive">
        Failed to load item: {err.message}
      </div>
    )
  }

  const { item, children } = q.data
  return (
    <div className="space-y-4">
      <Breadcrumb path={item.path ?? path} />
      <h1 className="text-lg font-semibold">{item.summary}</h1>
      <div className="text-sm text-muted-foreground">
        {item.source_type} · {item.status}
      </div>
      <section className="space-y-2">
        <h2 className="font-mono text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Children ({children.length})
        </h2>
        <div className="space-y-1">
          {children.map((c) => <ChildRow key={c.path} child={c} />)}
        </div>
      </section>
    </div>
  )
}
