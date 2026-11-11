import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'

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
            unless their role may bypass the list (Owner and Admin by default). Leave empty to allow any network. The list must include
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

export function SecuritySettingsPage() {
  const query = useQuery({ queryKey: ['security-settings'], queryFn: () => api.get('/api/v1/security-settings') })
  return (
    <>
      <PageHeader title="Security" description="Where staff may sign in from." />
      {query.isPending ? <LoadingState /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <AllowListForm settings={query.data} />}
    </>
  )
}
