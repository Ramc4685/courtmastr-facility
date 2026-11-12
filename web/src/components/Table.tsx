import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Button } from './Button'
import { ErrorState, LoadingState } from './States'

export type Column<T> = { header: string; cell: (row: T) => ReactNode; className?: string }
type Page<T> = { data: T[]; page: { next_cursor?: string | null; has_more: boolean } }

/** Keyset paging: we keep the cursors of the pages already seen so "Previous" can go back. */
export function useKeysetQuery<T>(key: readonly unknown[], fetchPage: (cursor: string | undefined) => Promise<Page<T>>) {
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined])
  const [keyText, setKeyText] = useState(JSON.stringify(key))
  if (JSON.stringify(key) !== keyText) {
    // filters changed: start again from the first page
    setKeyText(JSON.stringify(key))
    setCursors([undefined])
  }
  const cursor = cursors[cursors.length - 1]
  const query = useQuery({ queryKey: [...key, cursor], queryFn: () => fetchPage(cursor), placeholderData: keepPreviousData })
  const nextCursor = query.data?.page.has_more ? query.data.page.next_cursor : undefined
  return {
    query,
    pageNumber: cursors.length,
    hasPrev: cursors.length > 1,
    hasNext: Boolean(nextCursor),
    prev: () => setCursors((c) => (c.length > 1 ? c.slice(0, -1) : c)),
    next: () => nextCursor && setCursors((c) => [...c, nextCursor]),
  }
}

type TableProps<T> = {
  caption: string
  columns: Column<T>[]
  rowKey: (row: T) => string
  paging: ReturnType<typeof useKeysetQuery<T>>
  empty: ReactNode
}

export function Table<T>({ caption, columns, rowKey, paging, empty }: TableProps<T>) {
  const { query } = paging
  if (query.isPending) return <LoadingState />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const rows = query.data.data
  return (
    <div className="relative overflow-hidden rounded-lg border border-border bg-surface shadow-card">
      {/* Stale rows stay at full contrast (dimming them failed WCAG 1.4.3); a bar and aria-busy mark the refetch. */}
      {query.isPlaceholderData && <div aria-hidden="true" data-testid="table-updating" className="absolute inset-x-0 top-0 h-0.5 animate-pulse bg-primary" />}
      {rows.length === 0 ? (
        empty
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" aria-busy={query.isPlaceholderData || undefined}>
            <caption className="sr-only">{caption}</caption>
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                {columns.map((c) => (
                  <th key={c.header} scope="col" className={`px-4 py-2.5 font-semibold ${c.className ?? ''}`}>
                    {c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr key={rowKey(row)} className="hover:bg-surface-2/60">
                  {columns.map((c) => (
                    <td key={c.header} className={`px-4 py-3 align-middle ${c.className ?? ''}`}>
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(paging.hasPrev || paging.hasNext) && (
        <nav aria-label={`${caption} pages`} className="flex items-center justify-between border-t border-border px-4 py-2.5">
          <span className="text-xs text-muted">Page {paging.pageNumber}</span>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={paging.prev} disabled={!paging.hasPrev}>
              Previous
            </Button>
            <Button size="sm" variant="secondary" onClick={paging.next} disabled={!paging.hasNext}>
              Next
            </Button>
          </div>
        </nav>
      )}
    </div>
  )
}
