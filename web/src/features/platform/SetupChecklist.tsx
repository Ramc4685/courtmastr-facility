import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { Card } from '../../components/PageHeader'
import { useAuth } from '../../lib/auth'

/** First-run checklist (ONB-01): every tick is computed by the server from real data. Dismissing hides it for you only. */
export function SetupChecklist() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const allowed = can('platform.tenant.update')
  const query = useQuery({ queryKey: ['onboarding'], queryFn: () => api.get('/api/v1/onboarding/checklist'), enabled: allowed, retry: false })
  const dismiss = useMutation({
    mutationFn: () => api.put('/api/v1/onboarding/checklist/dismissal', { body: { is_dismissed: true } }),
    onSuccess: (data) => qc.setQueryData(['onboarding'], data),
  })
  const list = query.data
  if (!allowed || !list || list.is_dismissed || list.is_complete) return null
  return (
    <Card title="Set up your account" className="mb-8">
      <p className="mb-4 text-sm text-muted" id="setup-progress">
        {list.done_count} of {list.steps.length} done. Each step ticks itself once the thing exists.
      </p>
      <ol className="space-y-2" aria-describedby="setup-progress">
        {list.steps.map((step) => (
          <li key={step.key} className="flex items-center gap-3">
            <span
              aria-hidden="true"
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs ${step.is_done ? 'border-success bg-success text-on-primary' : 'border-border'}`}
            >
              {step.is_done ? '✓' : ''}
            </span>
            {step.is_done ? (
              <span className="text-muted line-through">{step.label}</span>
            ) : (
              <Link to={step.path} className="font-medium text-primary underline-offset-2 hover:underline">
                {step.label}
              </Link>
            )}
            <span className="sr-only">{step.is_done ? '(done)' : '(to do)'}</span>
          </li>
        ))}
      </ol>
      <Button variant="ghost" size="sm" className="mt-4" loading={dismiss.isPending} onClick={() => dismiss.mutate()}>
        Hide this checklist
      </Button>
    </Card>
  )
}
