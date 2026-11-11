import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Select } from '../../components/Field'
import { SanitizedHtml } from '../../components/SanitizedHtml'
import { LoadingState } from '../../components/States'
import { APP_NAME } from '../../lib/format'
import { SignerFields, emptySigner, signerReady } from './SignerFields'

/** The page an emailed signing link opens (DOC-04). The token arrives in the URL fragment, is removed from the
 * address bar at once and travels only in POST bodies (security-baseline 17.2). Opening the page does not use the
 * link up; accepting or declining does. */
export function PublicSignPage() {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '')
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname)
    document.title = `Review and sign · ${APP_NAME}`
  }, [])
  const view = useQuery({
    queryKey: ['public-document', token],
    queryFn: () => api.post('/api/v1/public/document-deliveries/open', { body: { token } }),
    enabled: Boolean(token),
    retry: false,
    staleTime: Infinity,
  })
  const [signer, setSigner] = useState(emptySigner())
  const [role, setRole] = useState<'client' | 'guardian'>('client')
  const [agreed, setAgreed] = useState(false)
  const decide = useMutation({
    mutationFn: (decision: 'accepted' | 'declined') =>
      api.post('/api/v1/public/document-deliveries/decision', {
        body: {
          token,
          decision,
          content_sha256: view.data?.content_sha256 ?? '',
          signer_name: signer.name.trim(),
          signer_role: view.data?.requires_guardian ? 'guardian' : role,
          // A drawn signature is sent with the typed name, which the record always keeps.
          typed_signature: (signer.method === 'typed_name' ? signer.typed : signer.name).trim(),
          signature_png: signer.method === 'drawn_signature' ? signer.png : null,
        },
      }),
  })

  const gone = (e: unknown) => e instanceof ApiError && ['token-invalid', 'token-expired', 'token-superseded'].includes(e.code ?? '')
  let content
  if (!token || gone(view.error)) {
    content = (
      <p role="alert">
        {view.error instanceof ApiError && view.error.code === 'token-superseded'
          ? 'A newer link was sent for this document. Please use the most recent email.'
          : 'This link is not valid any more. Links work once and expire; ask the facility to send a new one.'}
      </p>
    )
  } else if (view.isPending) {
    content = <LoadingState />
  } else if (view.error) {
    content = <p role="alert">{view.error.message}</p>
  } else if (decide.data) {
    content = (
      <p role="status" className="text-lg">
        {decide.data.status === 'declined' ? 'You declined this document. The facility has been told.' : 'Thank you. Your signature is recorded and a copy is kept on file.'}
      </p>
    )
  } else {
    const doc = view.data
    const guardian = doc.requires_guardian
    content = (
      <div className="space-y-6">
        <p className="text-muted">
          {doc.tenant_name} asks {guardian ? `a parent or guardian of ${doc.client_display_name}` : doc.client_display_name} to review and sign this document.
        </p>
        <article className="rounded-lg border border-border bg-surface p-5">
          <SanitizedHtml html={doc.body_html} />
        </article>
        {!guardian && (
          <Select
            label="I am signing as"
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
            options={[
              { value: 'client', label: doc.client_display_name },
              { value: 'guardian', label: `Parent or guardian of ${doc.client_display_name}` },
            ]}
          />
        )}
        <SignerFields role={guardian ? 'guardian' : role} value={signer} onChange={setSigner} />
        <Checkbox label={doc.acceptance_text} checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        {decide.error && (
          <p role="alert" className="text-danger">
            {decide.error.message}
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => decide.mutate('accepted')} disabled={!agreed || !signerReady(signer)} loading={decide.isPending && decide.variables === 'accepted'}>
            Accept and sign
          </Button>
          <Button variant="secondary" onClick={() => decide.mutate('declined')} disabled={!signer.name.trim()} loading={decide.isPending && decide.variables === 'declined'}>
            Decline
          </Button>
        </div>
        <p className="text-xs text-muted">The link expires {new Date(doc.expires_at).toLocaleString()}. Your name, the time, your IP address and device are recorded with your decision.</p>
      </div>
    )
  }
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="mb-6">{view.data?.title ?? 'Review and sign'}</h1>
      {content}
    </main>
  )
}
