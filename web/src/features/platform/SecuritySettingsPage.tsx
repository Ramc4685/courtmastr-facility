import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { api, ApiError, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { IdentityProvidersCard } from './IdentityProviders'

const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean)

function AllowListForm({ settings }: { settings: Schemas['SecuritySettings'] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const id = useId()
  const [text, setText] = useState(settings.staff_ip_allowlist.join('\n'))
  const save = useMutation({
    mutationFn: () => api.patch('/api/v1/security-settings', { body: { staff_ip_allowlist: lines(text) } }),
    onSuccess: (saved) => {
      qc.setQueryData(['security-settings'], saved)
      setText(saved.staff_ip_allowlist.join('\n'))
      toast('success', saved.staff_ip_allowlist.length ? 'Allowed networks saved.' : 'Staff can now sign in from anywhere.')
    },
  })
  // One field, so a problem on any line (or the self-lockout guard) shows as the field's error.
  const error = save.error instanceof ApiError ? (save.error.problem.errors?.[0]?.detail ?? save.error.message) : save.error?.message
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Card title="Staff sign-in networks" className="max-w-2xl">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <label htmlFor={id} className="block text-sm font-medium">
            Allowed networks
          </label>
          <textarea
            id={id}
            rows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-describedby={`${id}-hint${error ? ` ${id}-error` : ''}`}
            aria-invalid={error ? true : undefined}
            spellCheck={false}
            className="block w-full rounded border border-border bg-surface px-3 py-2 font-mono text-sm text-fg aria-[invalid=true]:border-danger"
          />
          <p id={`${id}-hint`} className="text-xs text-muted">
            One address or range per line, for example 203.0.113.0/24. Staff outside these networks cannot sign in or keep working,
            whatever their role, Owners included. Leave empty to allow any network. The list must include
            the address you are using now.
          </p>
          {error && (
            <p id={`${id}-error`} role="alert" className="text-xs font-medium text-danger">
              {error}
            </p>
          )}
        </div>
        <Button type="submit" loading={save.isPending}>
          Save networks
        </Button>
      </form>
    </Card>
  )
}

const POLICIES = [
  { value: 'privileged', label: 'Required for Owner and Admin' },
  { value: 'all', label: 'Required for all staff' },
  { value: 'optional', label: 'Optional for everyone' },
]

/** Who must use two-step verification, and how long an idle staff session lasts. Relaxing the policy is Owner-only. */
function SignInPolicyForm({ settings }: { settings: Schemas['SecuritySettings'] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [policy, setPolicy] = useState(settings.staff_mfa_policy)
  const [idle, setIdle] = useState(String(settings.staff_idle_timeout_min))
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/security-settings', { body: { staff_mfa_policy: policy, staff_idle_timeout_min: Number(idle) } }),
    onSuccess: (saved) => {
      qc.setQueryData(['security-settings'], saved)
      toast('success', 'Sign-in policy saved.')
    },
  })
  const error = save.error instanceof ApiError ? save.error : null
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Card title="Two-step verification and sessions" className="max-w-2xl">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && !error.problem.errors?.length && (
          <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
            {error.message}
          </p>
        )}
        <Select
          label="Two-step verification for staff"
          hint="Staff who need it and have not set it up are walked through it at their next sign-in. Members may always choose it."
          options={POLICIES}
          value={policy}
          onChange={(e) => setPolicy(e.target.value as typeof policy)}
        />
        <Input
          label="Sign staff out after inactivity (minutes)"
          hint="Between 15 and 60. Staff sessions end after 12 hours regardless."
          type="number"
          min={15}
          max={60}
          required
          value={idle}
          error={fieldErrors(save.error).staff_idle_timeout_min}
          onChange={(e) => setIdle(e.target.value)}
        />
        <Button type="submit" loading={save.isPending}>
          Save policy
        </Button>
      </form>
    </Card>
  )
}

export function SecuritySettingsPage() {
  const query = useQuery({ queryKey: ['security-settings'], queryFn: () => api.get('/api/v1/security-settings') })
  return (
    <>
      <PageHeader title="Security" description="How and where staff may sign in." />
      {query.isPending ? <LoadingState /> : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : (
        <div className="space-y-6">
          <SignInPolicyForm settings={query.data} />
          <AllowListForm settings={query.data} />
          <IdentityProvidersCard />
        </div>
      )}
    </>
  )
}
