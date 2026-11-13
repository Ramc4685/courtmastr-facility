import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { ErrorState, LoadingState } from '../../components/States'
import { APP_NAME, formatDateTime } from '../../lib/format'
import { BestsTable, ResultsTable } from './ProgressPage'

/** A shared progress link (FIT-05), no sign-in. Like the pay link, the token arrives in the URL fragment (never
 * sent to a server or a Referer), is read once, removed from the address bar, and posted in the body. */
export function PublicProgressPage() {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '')
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname)
  }, [])
  const shared = useQuery({ queryKey: ['progress-share', token], queryFn: () => api.post('/api/v1/public/progress-shares/lookup', { body: { token } }), enabled: Boolean(token), retry: false })
  const title = shared.data ? `${shared.data.first_name}'s progress` : 'Shared progress'
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`
  }, [title])

  const body = () => {
    if (!token) return <ErrorState error={new Error('This link is incomplete. Open it again from the message you were sent.')} />
    if (shared.isPending) return <LoadingState />
    if (shared.isError) return <ErrorState error={shared.error instanceof ApiError && shared.error.status === 404 ? new Error('This link has expired or was turned off.') : shared.error} />
    const p = shared.data
    return (
      <div className="space-y-8">
        <p className="text-muted">Read-only. This link works until {formatDateTime(p.expires_at, p.time_zone)}.</p>
        <section aria-labelledby="bests" className="space-y-3">
          <h2 id="bests">Personal bests</h2>
          <BestsTable bests={p.bests} zone={p.time_zone} />
        </section>
        <section aria-labelledby="results" className="space-y-3">
          <h2 id="results">Results</h2>
          <ResultsTable results={p.results} zone={p.time_zone} />
        </section>
      </div>
    )
  }
  return (
    <div className="min-h-screen bg-bg">
      <main className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="mb-4">{title}</h1>
        {body()}
      </main>
    </div>
  )
}
