import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import { PageHeader } from '../../components/PageHeader'

/** QuickBooks sends the browser here after consent. The page posts state, code and company id to the API in the
 * signed-in session of the staff user who started (a GET must not change state), once, then goes back. */
export function QuickBooksCallbackPage() {
  const [params] = useSearchParams()
  const [result, setResult] = useState<{ ok: boolean; message: string; back: string } | null>(null)
  const sent = useRef(false)
  useEffect(() => {
    if (window.location.search) window.history.replaceState(window.history.state, '', window.location.pathname)
    if (sent.current) return // the state works once (StrictMode runs effects twice)
    sent.current = true
    const state = params.get('state')
    if (!state) return setResult({ ok: false, message: 'This QuickBooks link is incomplete.', back: '/integrations' })
    api
      .post('/api/v1/external-connections/oauth/callback', {
        body: { state, code: params.get('code'), realm_id: params.get('realmId') ?? params.get('realm_id'), error: params.get('error') },
      })
      .then(
        (out) => {
          const back = new URL(out.return_url, window.location.origin)
          const path = back.origin === window.location.origin ? back.pathname + back.search : '/integrations'
          if (out.status === 'connected') window.location.replace(path)
          else setResult({ ok: false, message: 'QuickBooks did not connect. Try again from Integrations.', back: path })
        },
        (e: unknown) => setResult({ ok: false, message: e instanceof Error ? e.message : 'QuickBooks did not connect.', back: '/integrations' }),
      )
  }, [params])
  return (
    <>
      <PageHeader title="Connecting QuickBooks" />
      {result ? (
        <div role="alert" className="space-y-3">
          <p>{result.message}</p>
          <Link to={result.back} className="font-medium text-primary underline-offset-2 hover:underline">
            Back to Integrations
          </Link>
        </div>
      ) : (
        <p role="status">One moment…</p>
      )}
    </>
  )
}
