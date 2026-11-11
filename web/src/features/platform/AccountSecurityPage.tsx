import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Input } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { codeMessage, EnrolmentDetails, RecoveryCodes, type Enrolment } from '../auth/mfa'

const KEY = ['me-mfa']

/** The signed-in user's own second factor. Every change here needs a recent check, which the API client asks for. */
function TwoStepCard({ status }: { status: Schemas['MfaStatus'] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null)
  const [codes, setCodes] = useState<string[] | null>(null)
  const [code, setCode] = useState('')
  const [confirmOff, setConfirmOff] = useState(false)
  const refresh = () => qc.invalidateQueries({ queryKey: KEY })

  const start = useMutation({ mutationFn: () => api.post('/api/v1/me/mfa/totp'), onSuccess: setEnrolment })
  const confirm = useMutation({
    mutationFn: () => api.post('/api/v1/me/mfa/totp/confirm', { body: { code } }),
    onSuccess: (out) => {
      setEnrolment(null)
      setCode('')
      setCodes(out.recovery_codes)
    },
  })
  const regenerate = useMutation({ mutationFn: () => api.post('/api/v1/me/mfa/recovery-codes'), onSuccess: (out) => setCodes(out.recovery_codes) })
  const disable = useMutation({
    mutationFn: () => api.delete('/api/v1/me/mfa/totp'),
    onSuccess: () => {
      setConfirmOff(false)
      toast('success', 'Two-step verification is off.')
      void refresh()
    },
  })
  const failed = start.error ?? regenerate.error ?? disable.error

  const submit = (e: FormEvent) => {
    e.preventDefault()
    confirm.mutate()
  }

  let body
  if (codes)
    body = (
      <RecoveryCodes
        codes={codes}
        onDone={() => {
          setCodes(null)
          void refresh()
        }}
      />
    )
  else if (enrolment)
    body = (
      <form onSubmit={submit} className="space-y-4" noValidate>
        <EnrolmentDetails enrolment={enrolment} />
        <Input label="Code from the app" autoComplete="one-time-code" required value={code} error={codeMessage(confirm.error)} onChange={(e) => setCode(e.target.value)} />
        <div className="flex gap-2">
          <Button type="submit" loading={confirm.isPending}>
            Turn on
          </Button>
          <Button variant="secondary" onClick={() => setEnrolment(null)}>
            Cancel
          </Button>
        </div>
      </form>
    )
  else if (status.enrolled)
    body = (
      <div className="space-y-4">
        <p>
          <Badge tone="success">On</Badge>
          <span className="ml-2 text-muted">since {formatDateTime(status.confirmed_at)}</span>
        </p>
        <p className="text-muted">{status.recovery_codes_remaining} of 10 recovery codes left.</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" loading={regenerate.isPending} onClick={() => regenerate.mutate()}>
            New recovery codes
          </Button>
          {!status.required && (
            <Button variant="danger" onClick={() => setConfirmOff(true)}>
              Turn off
            </Button>
          )}
        </div>
        {status.required && <p className="text-sm text-muted">Your role requires two-step verification, so it cannot be turned off.</p>}
      </div>
    )
  else
    body = (
      <div className="space-y-4">
        <p>
          <Badge tone={status.required ? 'warning' : 'neutral'}>Off</Badge>
          <span className="ml-2 text-muted">Add a code from an authenticator app to every sign-in.</span>
        </p>
        <Button loading={start.isPending} onClick={() => start.mutate()}>
          Turn on two-step verification
        </Button>
      </div>
    )

  return (
    <Card title="Two-step verification" className="max-w-2xl">
      {failed && (
        <p role="alert" className="mb-4 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {codeMessage(failed)}
        </p>
      )}
      {body}
      <ConfirmDialog
        open={confirmOff}
        title="Turn off two-step verification?"
        confirmLabel="Turn off"
        danger
        busy={disable.isPending}
        onConfirm={() => disable.mutate()}
        onClose={() => setConfirmOff(false)}
      >
        Sign-in will need only your password or an email link. Your recovery codes stop working.
      </ConfirmDialog>
    </Card>
  )
}

export function AccountSecurityPage() {
  const query = useQuery({ queryKey: KEY, queryFn: () => api.get('/api/v1/me/mfa') })
  return (
    <>
      <PageHeader title="Your sign-in security" description="How you prove it is you when you sign in." />
      {query.isPending ? <LoadingState /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <TwoStepCard status={query.data} />}
    </>
  )
}
