import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { Input } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'

/** Every operation an API key may call and the scopes that open it, generated from the routes (INT-01). */
export function ApiReferencePanel() {
  const [filter, setFilter] = useState('')
  const ops = useQuery({ queryKey: ['api-reference'], queryFn: () => api.get('/api/v1/api-reference'), staleTime: 5 * 60_000 })
  const needle = filter.trim().toLowerCase()
  const rows = (ops.data ?? []).filter((o) => !needle || [o.method, o.path, o.summary, o.tag, ...o.scopes].some((v) => v.toLowerCase().includes(needle)))
  return (
    <section aria-labelledby="api-reference-heading" className="grid gap-4">
      <div>
        <h2 id="api-reference-heading" className="text-lg font-semibold">
          API reference
        </h2>
        <p className="text-sm text-muted">What a key can call. A key needs any one of the listed scopes for an operation.</p>
      </div>
      <Input label="Filter" type="search" className="max-w-sm" value={filter} hint="Method, path, scope or area." onChange={(e) => setFilter(e.target.value)} />
      {ops.isPending ? (
        <LoadingState />
      ) : ops.isError ? (
        <ErrorState error={ops.error} onRetry={() => void ops.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title="No operations match" />
      ) : (
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">API operations and their scopes</caption>
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-3 py-2">
                  Method
                </th>
                <th scope="col" className="px-3 py-2">
                  Path
                </th>
                <th scope="col" className="hidden px-3 py-2 md:table-cell">
                  Summary
                </th>
                <th scope="col" className="px-3 py-2">
                  Scopes
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((o) => (
                <tr key={o.operation_id}>
                  <td className="px-3 py-2 font-mono text-xs font-semibold">{o.method.toUpperCase()}</td>
                  <td className="break-all px-3 py-2 font-mono text-xs">{o.path}</td>
                  <td className="hidden px-3 py-2 md:table-cell">{o.summary}</td>
                  <td className="px-3 py-2 font-mono text-xs">{o.scopes.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
