import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'

type Adapter = Schemas['AdapterOut']
const TONE: Record<Adapter['status'], Tone> = { connected: 'success', simulated: 'info', not_configured: 'neutral' }
const STATUS: Record<Adapter['status'], string> = { connected: 'Connected', simulated: 'Simulated', not_configured: 'Not configured' }

/** Every outside system the app talks to through a port, and what is behind that port today. */
export function DirectoryPanel() {
  const qc = useQueryClient()
  const toast = useToast()
  const adapters = useQuery({ queryKey: ['integration-adapters'], queryFn: () => api.get('/api/v1/integration-adapters') })
  const connect = useMutation({
    mutationFn: () => api.post('/api/v1/external-connections', { body: { provider: 'accounting_file' } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['integration-adapters'] })
      toast('success', 'Accounting file export connected.')
    },
    onError: (e) => toast('error', e.message),
  })

  if (adapters.isPending) return <LoadingState />
  if (adapters.isError) return <ErrorState error={adapters.error} onRetry={() => void adapters.refetch()} />
  return (
    <section aria-labelledby="directory-heading">
      <h2 id="directory-heading" className="text-lg font-semibold">
        Connected systems
      </h2>
      <p className="mb-4 text-sm text-muted">Simulated adapters record what they would have sent, so flows can be tried without a live account.</p>
      <ul className="grid gap-3 md:grid-cols-2">
        {adapters.data.map((a) => (
          <li key={a.port} className="rounded-lg border border-border bg-surface p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-medium">{a.label}</h3>
              <Badge tone={TONE[a.status]}>{STATUS[a.status]}</Badge>
            </div>
            <p className="mt-1 text-sm text-muted">{a.detail}</p>
            {a.port === 'accounting' && a.status !== 'connected' && (
              <Button size="sm" variant="secondary" className="mt-3" loading={connect.isPending} onClick={() => connect.mutate()}>
                Connect file export
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
