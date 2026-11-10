import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile, fieldErrors, uploadFile, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Dialog } from '../../components/Dialog'
import { SanitizedHtml } from '../../components/SanitizedHtml'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { ROLE_LABEL, SignerFields, emptySigner, signerReady, toSigner, type SignerState } from './SignerFields'

type Doc = Schemas['ClientDocumentOut']
type Client = Schemas['ClientOut']

const STATUS: Record<string, [Tone, string]> = {
  pending: ['warning', 'Awaiting signature'],
  accepted: ['success', 'Signed'],
  declined: ['danger', 'Declined'],
  expired: ['neutral', 'Expired'],
  voided: ['neutral', 'Voided'],
}

const docsKey = (clientId: string) => ['client-documents', clientId]

/** Waiver indicator for the profile header (DOC-15): override and expiry already applied by the server. */
export function WaiverBadge({ clientId }: { clientId: string }) {
  const { can } = useAuth()
  const query = useQuery({
    queryKey: ['client-document-statuses', clientId],
    queryFn: () => api.get('/api/v1/client-document-statuses', { query: { 'client_id[in]': clientId } }),
    enabled: can('documents.document.read'),
  })
  const status = query.data?.data[0]
  if (!status) return null
  return status.is_waiver_on_file ? (
    <Badge tone="success">Waiver on file{status.waiver_valid_until_on ? ` until ${status.waiver_valid_until_on}` : ''}</Badge>
  ) : (
    <Badge tone="danger">No valid waiver</Badge>
  )
}

function IssueDialog({ client, onClose }: { client: Client; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { me } = useAuth()
  const templates = useQuery({ queryKey: ['document-templates', 'active'], queryFn: () => api.get('/api/v1/document-templates', { query: { status: 'active', limit: 100 } }) })
  const emails = (client.emails ?? []).filter((e) => e.verified_at).map((e) => e.email)
  const [form, setForm] = useState({
    template_id: '',
    location_id: client.home_location_id ?? me?.locations?.[0]?.id ?? '',
    method: 'checkbox' as 'checkbox' | 'email_link',
    email: emails[0] ?? '',
  })
  const issue = useMutation({
    mutationFn: () =>
      api.post('/api/v1/client-documents', {
        body: {
          client_id: client.id,
          location_id: form.location_id,
          template_id: form.template_id,
          acceptance_method: form.method,
          recipient_emails: form.method === 'email_link' ? [form.email] : null,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: docsKey(client.id) })
      toast('success', form.method === 'email_link' ? 'Signing link sent' : 'Document ready to sign')
      onClose()
    },
  })
  const errors = fieldErrors(issue.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title="Issue a document"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => issue.mutate()} loading={issue.isPending} disabled={!form.template_id || !form.location_id || (form.method === 'email_link' && !form.email)}>
            Issue
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Select label="Template" value={form.template_id} error={errors.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })} placeholder="Choose a template" options={(templates.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))} />
        <Select label="Location" value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })} options={(me?.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} />
        <Select
          label="How will they sign?"
          value={form.method}
          onChange={(e) => setForm({ ...form, method: e.target.value as typeof form.method })}
          options={[
            { value: 'checkbox', label: 'Here, in person' },
            { value: 'email_link', label: 'Email a single-use link' },
          ]}
        />
        {form.method === 'email_link' &&
          (emails.length ? (
            <Select label="Send to" hint="Only confirmed addresses of the client or a guardian." value={form.email} error={errors.recipient_emails} onChange={(e) => setForm({ ...form, email: e.target.value })} options={emails.map((e) => ({ value: e, label: e }))} />
          ) : (
            <p className="text-sm text-danger">This client has no confirmed email address. Confirm one first, or sign in person.</p>
          ))}
        {issue.error && !Object.keys(errors).length && <p className="text-sm text-danger">{issue.error.message}</p>}
      </div>
    </Dialog>
  )
}

function SignDialog({ doc, onClose }: { doc: Doc; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const decided = new Set(doc.acceptances.map((a) => a.signer_role))
  const roles = doc.required_roles.filter((r) => !decided.has(r))
  const relationships = useQuery({
    queryKey: ['clients', doc.client_id, 'relationships'],
    queryFn: () => api.get('/api/v1/clients/{client_id}/relationships', { path: { client_id: doc.client_id } }),
    enabled: roles.includes('guardian'),
  })
  const guardians = (relationships.data ?? [])
    .filter((r) => r.status === 'active' && (r.acting_rights === 'other_for_this' || r.acting_rights === 'both'))
    .map((r) => ({ id: r.other_client_id, name: r.other_client_name }))
  const [signers, setSigners] = useState<Record<string, SignerState>>(() =>
    Object.fromEntries(roles.map((r) => [r, emptySigner(r === 'client' ? doc.client_name : '')])),
  )
  const [agreed, setAgreed] = useState(false)
  const at = (role: string) => signers[role] ?? emptySigner()
  const submit = useMutation({
    mutationFn: (decision: 'accepted' | 'declined') =>
      api.post('/api/v1/client-documents/{document_id}/acceptances', {
        path: { document_id: doc.id },
        body: { content_sha256: doc.content_sha256, signers: roles.map((r) => toSigner(r, at(r), decision)) },
      }),
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: docsKey(doc.client_id) })
      void qc.invalidateQueries({ queryKey: ['client-document-statuses', doc.client_id] })
      toast('success', saved.status === 'accepted' ? 'Signed' : saved.status === 'declined' ? 'Declined' : 'Signature recorded')
      onClose()
    },
  })
  const ready = agreed && roles.every((r) => signerReady(at(r)))
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={`Sign: ${doc.title}`}
      description={`For ${doc.client_name}. You are recorded as the witness.`}
      footer={
        <>
          <Button variant="secondary" onClick={() => submit.mutate('declined')} disabled={!roles.every((r) => at(r).name.trim())} loading={submit.isPending && submit.variables === 'declined'}>
            Record decline
          </Button>
          <Button onClick={() => submit.mutate('accepted')} disabled={!ready} loading={submit.isPending && submit.variables === 'accepted'}>
            Sign document
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="rounded border border-border p-4">
          <SanitizedHtml html={doc.body_html} />
        </div>
        {doc.requires_guardian && <p className="text-sm">This client is a minor: a parent or guardian must sign.</p>}
        {roles.map((r) => (
          <SignerFields key={r} role={r} value={at(r)} guardians={r === 'guardian' ? guardians : undefined} onChange={(next) => setSigners({ ...signers, [r]: next })} />
        ))}
        <Checkbox label={doc.acceptance_text} checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        {submit.error && <p className="text-sm text-danger">{submit.error.message}</p>}
      </div>
    </Dialog>
  )
}

function SendDialog({ doc, client, onClose }: { doc: Doc; client: Client; onClose: () => void }) {
  const toast = useToast()
  const emails = (client.emails ?? []).filter((e) => e.verified_at).map((e) => e.email)
  const [email, setEmail] = useState(emails[0] ?? '')
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/client-documents/{document_id}/deliveries', { path: { document_id: doc.id }, body: { recipient_emails: [email] } }),
    onSuccess: () => {
      toast('success', 'Signing link sent; any earlier link stops working')
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title="Email a signing link"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => send.mutate()} disabled={!email} loading={send.isPending}>
            Send link
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Input label="Recipient email" hint="A confirmed address of the client or a guardian." type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={fieldErrors(send.error).recipient_emails} />
        {send.error && !fieldErrors(send.error).recipient_emails && <p className="text-sm text-danger">{send.error.message}</p>}
      </div>
    </Dialog>
  )
}

function UploadDialog({ client, doc, onClose }: { client: Client; doc?: Doc; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { me } = useAuth()
  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const upload = useMutation({
    mutationFn: async () => {
      const target =
        doc ??
        (await api.post('/api/v1/client-documents', {
          body: { client_id: client.id, location_id: client.home_location_id ?? me?.locations?.[0]?.id ?? '', title, acceptance_method: 'paper' },
        }))
      return uploadFile('/api/v1/client-documents/{document_id}/paper-scan', { document_id: target.id }, file as File)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: docsKey(client.id) })
      void qc.invalidateQueries({ queryKey: ['client-document-statuses', client.id] })
      toast('success', 'Uploaded and marked as signed on paper')
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={doc ? `Attach the signed paper copy: ${doc.title}` : 'Upload a signed document'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => upload.mutate()} disabled={!file || (!doc && !title)} loading={upload.isPending}>
            Upload
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {!doc && <Input label="Title" value={title} onChange={(e) => setTitle(e.target.value)} required />}
        <div className="space-y-1.5">
          <label htmlFor="doc-file" className="block text-sm font-medium">
            File (PDF, JPEG or PNG, up to 20 MB)
          </label>
          <input id="doc-file" type="file" accept="application/pdf,image/jpeg,image/png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm" />
        </div>
        {upload.error && <p className="text-sm text-danger">{upload.error.message}</p>}
      </div>
    </Dialog>
  )
}

type Open = { kind: 'issue' } | { kind: 'upload'; doc?: Doc } | { kind: 'sign'; doc: Doc } | { kind: 'send'; doc: Doc } | null

export function ClientDocumentsTab({ client }: { client: Client }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const [showDeleted, setShowDeleted] = useState(false)
  const [open, setOpen] = useState<Open>(null)
  const query = useQuery({
    queryKey: [...docsKey(client.id), showDeleted],
    queryFn: () => api.get('/api/v1/client-documents', { query: { client_id: client.id, is_deleted: showDeleted, limit: 100 } }),
  })
  const changed = () => {
    void qc.invalidateQueries({ queryKey: docsKey(client.id) })
    void qc.invalidateQueries({ queryKey: ['client-document-statuses', client.id] })
  }
  const act = useMutation({
    mutationFn: ({ doc, action }: { doc: Doc; action: 'void' | 'delete' | 'restore' | 'renew' | 'unpaper' }) => {
      const path = { document_id: doc.id }
      if (action === 'void') return api.post('/api/v1/client-documents/{document_id}/void', { path })
      if (action === 'delete') return api.delete('/api/v1/client-documents/{document_id}', { path })
      if (action === 'restore') return api.post('/api/v1/client-documents/{document_id}/restore', { path })
      if (action === 'unpaper') return api.delete('/api/v1/client-documents/{document_id}/paper-scan', { path })
      // Renewal issues the template's current version again; the old record stays as history.
      return api.post('/api/v1/client-documents', {
        body: { client_id: doc.client_id, location_id: doc.location_id, template_id: doc.template_id, acceptance_method: 'checkbox' },
      })
    },
    onSuccess: (_, { action }) => {
      changed()
      toast('success', { void: 'Voided', delete: 'Deleted; restore it from Show deleted', restore: 'Restored', renew: 'Renewal issued', unpaper: 'Returned to pending' }[action])
    },
    onError: (e) => toast('error', e.message),
  })
  const download = (doc: Doc, variant: 'rendered' | 'paper_scan') =>
    downloadFile('/api/v1/client-documents/{document_id}/file', { path: { document_id: doc.id }, query: { variant } }, `${doc.title}.pdf`).catch((e: Error) =>
      toast('error', e.message),
    )

  const live = client.status === 'active' && !client.merged_into_id && !client.erased_at
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Checkbox label="Show deleted (restorable)" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
        {live && can('documents.document.generate') && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setOpen({ kind: 'upload' })}>
              Upload document
            </Button>
            <Button onClick={() => setOpen({ kind: 'issue' })}>Issue document</Button>
          </div>
        )}
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data.data.length === 0 ? (
        <EmptyState title={showDeleted ? 'Nothing deleted' : 'No documents yet'}>{!showDeleted && 'Issue a waiver to sign here or by email, or upload a signed paper copy.'}</EmptyState>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {query.data.data.map((doc) => {
            const [tone, label] = STATUS[doc.status] ?? ['neutral', doc.status]
            const signedBy = doc.acceptances.filter((a) => a.decision === 'accepted').map((a) => `${a.signer_name} (${ROLE_LABEL[a.signer_role]})`)
            return (
              <li key={doc.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="space-y-1">
                  <p className="font-medium">
                    {doc.title} <Badge tone={tone}>{label}</Badge> {doc.is_paper_signed && <Badge>Paper</Badge>}
                  </p>
                  <p className="text-xs text-muted">
                    Issued {formatDateTime(doc.issued_at)}
                    {doc.decided_at && ` · decided ${formatDateTime(doc.decided_at)}`}
                    {doc.expires_on && ` · valid until ${doc.expires_on}`}
                    {signedBy.length > 0 && ` · signed by ${signedBy.join(', ')}`}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {showDeleted ? (
                    can('documents.document.void') && (
                      <Button size="sm" variant="secondary" onClick={() => act.mutate({ doc, action: 'restore' })}>
                        Restore
                      </Button>
                    )
                  ) : (
                    <>
                      {doc.status === 'pending' && doc.body_html && can('documents.document.collect_signature') && (
                        <>
                          <Button size="sm" onClick={() => setOpen({ kind: 'sign', doc })}>
                            Sign now
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setOpen({ kind: 'send', doc })}>
                            Email link
                          </Button>
                        </>
                      )}
                      {doc.status === 'pending' && can('documents.document.collect_signature') && (
                        <Button size="sm" variant="secondary" onClick={() => setOpen({ kind: 'upload', doc })}>
                          Attach paper copy
                        </Button>
                      )}
                      {doc.is_paper_signed && doc.status === 'accepted' && doc.acceptance_method === 'paper' && can('documents.document.collect_signature') && (
                        <Button size="sm" variant="secondary" onClick={() => act.mutate({ doc, action: 'unpaper' })}>
                          Clear paper flag
                        </Button>
                      )}
                      {doc.rendered_file_id && (
                        <Button size="sm" variant="secondary" onClick={() => void download(doc, 'rendered')}>
                          Download PDF
                        </Button>
                      )}
                      {doc.paper_scan_file_id && (
                        <Button size="sm" variant="secondary" onClick={() => void download(doc, 'paper_scan')}>
                          Paper copy
                        </Button>
                      )}
                      {doc.template_id && ['accepted', 'expired'].includes(doc.status) && can('documents.document.generate') && (
                        <Button size="sm" variant="secondary" onClick={() => act.mutate({ doc, action: 'renew' })}>
                          Renew
                        </Button>
                      )}
                      {can('documents.document.void') && !['voided', 'expired'].includes(doc.status) && (
                        <Button size="sm" variant="secondary" onClick={() => act.mutate({ doc, action: 'void' })}>
                          Void
                        </Button>
                      )}
                      {can('documents.document.void') && (
                        <Button size="sm" variant="secondary" onClick={() => act.mutate({ doc, action: 'delete' })}>
                          Delete
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {open?.kind === 'issue' && <IssueDialog client={client} onClose={() => setOpen(null)} />}
      {open?.kind === 'upload' && <UploadDialog client={client} doc={open.doc} onClose={() => setOpen(null)} />}
      {open?.kind === 'sign' && <SignDialog doc={open.doc} onClose={() => setOpen(null)} />}
      {open?.kind === 'send' && <SendDialog doc={open.doc} client={client} onClose={() => setOpen(null)} />}
    </div>
  )
}
