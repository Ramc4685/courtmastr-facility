import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { SanitizedHtml } from '../../components/SanitizedHtml'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { STATUS_TONE } from './TemplatesPage'

type Template = Schemas['DocumentTemplateOut']
type Block = Schemas['SignatureBlock']

// Mirrors MERGE_FIELDS in backend documents/domain/content.py; the server refuses any other token on save.
export const MERGE_FIELDS = [
  ['client.full_name', 'Client full name'],
  ['client.first_name', 'Client first name'],
  ['client.last_name', 'Client last name'],
  ['client.member_number', 'Member number'],
  ['client.birth_date', 'Client birth date'],
  ['location.name', 'Location name'],
  ['organization.name', 'Organization name'],
  ['document.date', 'Date issued'],
] as const

// Toolbar actions wrap the selection in an allowed tag. A plain-text editor with markup buttons, not WYSIWYG:
// what is saved is exactly the (sanitised) HTML shown in the preview.
const TOOLS: [string, string, string][] = [
  ['Heading', '<h2>', '</h2>'],
  ['Paragraph', '<p>', '</p>'],
  ['Bold', '<strong>', '</strong>'],
  ['Italic', '<em>', '</em>'],
  ['List item', '<li>', '</li>'],
  ['Bulleted list', '<ul>\n', '\n</ul>'],
]

function Details({ template }: { template: Template }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    name: template.name,
    is_waiver: template.is_waiver,
    validity: template.signature_validity_days?.toString() ?? '',
    requires_guardian_for_minors: template.requires_guardian_for_minors,
    minor_age_years: template.minor_age_years.toString(),
  })
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/document-templates/{template_id}', {
        path: { template_id: template.id },
        body: {
          name: form.name,
          is_waiver: form.is_waiver,
          signature_validity_days: form.validity ? Number(form.validity) : null,
          requires_guardian_for_minors: form.requires_guardian_for_minors,
          minor_age_years: Number(form.minor_age_years),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['document-templates'] })
      toast('success', 'Template details saved')
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <Card title="Details">
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Input label="Name" value={form.name} error={errors.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input label="Valid for (days)" hint="Empty: never expires." type="number" min={1} value={form.validity} onChange={(e) => setForm({ ...form, validity: e.target.value })} />
        <Checkbox label="Liability waiver" disabled={template.kind === 'consent'} checked={form.is_waiver} onChange={(e) => setForm({ ...form, is_waiver: e.target.checked })} />
        <Checkbox label="Minors need a parent or guardian to sign" checked={form.requires_guardian_for_minors} onChange={(e) => setForm({ ...form, requires_guardian_for_minors: e.target.checked })} />
        <Input label="Minor under age" type="number" min={1} max={25} value={form.minor_age_years} onChange={(e) => setForm({ ...form, minor_age_years: e.target.value })} />
        <div className="flex items-end">
          <Button type="submit" variant="secondary" loading={save.isPending}>
            Save details
          </Button>
        </div>
      </form>
    </Card>
  )
}

type Version = Schemas['DocumentTemplateVersionOut']

/** Edits the open draft if there is one, else starts from the published version. */
function Editor({ template, start, onSaved }: { template: Template; start: Version | null | undefined; onSaved: () => void }) {
  const toast = useToast()
  const area = useRef<HTMLTextAreaElement>(null)
  const [body, setBody] = useState(start?.body_html ?? '<h2>Assumption of risk</h2>\n<p>I, {{client.full_name}}, ...</p>')
  const [acceptance, setAcceptance] = useState(start?.acceptance_text ?? 'I have read and agree to these terms.')
  const [note, setNote] = useState('')
  const roles = new Set((start?.signature_blocks as Block[] | undefined)?.map((b) => b.role) ?? ['client'])
  const [guardian, setGuardian] = useState(roles.has('guardian'))
  const [coSigner, setCoSigner] = useState(roles.has('co_signer'))
  const [field, setField] = useState('')

  const insert = (before: string, after = '') => {
    const el = area.current
    if (!el) return
    const { selectionStart: a, selectionEnd: b } = el
    const next = body.slice(0, a) + before + body.slice(a, b) + after + body.slice(b)
    setBody(next)
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(a + before.length, b + before.length)
    })
  }
  const blocks: Block[] = [{ role: 'client', label: 'Participant' }]
  if (guardian) blocks.push({ role: 'guardian', label: 'Parent or guardian' })
  if (coSigner) blocks.push({ role: 'co_signer', label: 'Co-signer' })
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/document-templates/{template_id}/draft', {
        path: { template_id: template.id },
        body: { body_html: body, acceptance_text: acceptance, change_note: note || null, signature_blocks: blocks },
      }),
    onSuccess: (draft) => {
      setBody(draft.body_html)
      toast('success', `Draft version ${draft.version_number} saved`)
      onSaved()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Content">
        <div className="space-y-4">
          <div role="toolbar" aria-label="Formatting" className="flex flex-wrap gap-2">
            {TOOLS.map(([label, a, b]) => (
              <Button key={label} size="sm" variant="secondary" onClick={() => insert(a, b)}>
                {label}
              </Button>
            ))}
          </div>
          <div className="flex items-end gap-2">
            <Select label="Merge field" className="flex-1" value={field} onChange={(e) => setField(e.target.value)} placeholder="Choose a field" options={MERGE_FIELDS.map(([value, label]) => ({ value, label }))} />
            <Button variant="secondary" disabled={!field} onClick={() => insert(`{{${field}}}`)}>
              Insert
            </Button>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="doc-body" className="block text-sm font-medium">
              Document text (HTML)
            </label>
            <textarea
              id="doc-body"
              ref={area}
              rows={16}
              value={body}
              aria-invalid={errors.body_html ? true : undefined}
              aria-describedby={errors.body_html ? 'doc-body-error' : 'doc-body-hint'}
              onChange={(e) => setBody(e.target.value)}
              className="block w-full rounded border border-border bg-surface p-3 font-mono text-xs text-fg"
            />
            <p id="doc-body-hint" className="text-xs text-muted">
              Headings, paragraphs, emphasis, lists, links and tables are kept; anything else is removed on save.
            </p>
            {errors.body_html && (
              <p id="doc-body-error" className="text-xs font-medium text-danger">
                {errors.body_html}
              </p>
            )}
          </div>
          <Input label="Acceptance statement" hint="Shown above the signature." value={acceptance} error={errors.acceptance_text} onChange={(e) => setAcceptance(e.target.value)} />
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Signatures</legend>
            <Checkbox label="Client (always)" checked disabled />
            <Checkbox label="Parent or guardian block" hint="Required instead of the client's when the client is a minor." checked={guardian} onChange={(e) => setGuardian(e.target.checked)} />
            <Checkbox label="Co-signer block" checked={coSigner} onChange={(e) => setCoSigner(e.target.checked)} />
          </fieldset>
          <Input label="Change note" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={template.status === 'archived'}>
            Save draft
          </Button>
        </div>
      </Card>
      <Card title="Preview">
        <SanitizedHtml html={body} />
        <p className="mt-4 font-semibold">{acceptance}</p>
        <ul className="mt-3 space-y-1 text-muted">
          {blocks.map((b) => (
            <li key={b.role}>{b.label}: ____________________</li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

export function TemplateEditorPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['document-templates', id]
  const query = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/document-templates/{template_id}', { path: { template_id: id } }) })
  const versions = useQuery({
    queryKey: [...key, 'versions'],
    queryFn: () => api.get('/api/v1/document-templates/{template_id}/versions', { path: { template_id: id } }),
  })
  const refresh = () => void qc.invalidateQueries({ queryKey: ['document-templates'] })
  const act = useMutation({
    mutationFn: (action: 'publish' | 'archive' | 'restore') =>
      action === 'publish'
        ? api.post('/api/v1/document-templates/{template_id}/publish', { path: { template_id: id } })
        : action === 'archive'
          ? api.post('/api/v1/document-templates/{template_id}/archive', { path: { template_id: id } })
          : api.post('/api/v1/document-templates/{template_id}/restore', { path: { template_id: id } }),
    onSuccess: (_, action) => {
      refresh()
      toast('success', { publish: 'Published', archive: 'Archived', restore: 'Restored' }[action])
    },
    onError: (e) => toast('error', e.message),
  })
  if (query.isPending) return <LoadingState />
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const t = query.data
  return (
    <>
      <PageHeader
        title={t.name}
        description={
          <span className="flex items-center gap-2">
            <Badge tone={STATUS_TONE[t.status as keyof typeof STATUS_TONE] ?? 'neutral'}>{t.status}</Badge>
            {t.current_version ? `Published version ${t.current_version.version_number}` : 'Not published yet'}
            {t.has_draft && <Badge tone="warning">Unpublished draft</Badge>}
          </span>
        }
        actions={
          <div className="flex gap-2">
            {t.status !== 'archived' && (
              <Button disabled={!t.has_draft} loading={act.isPending && act.variables === 'publish'} onClick={() => act.mutate('publish')}>
                Publish draft
              </Button>
            )}
            {t.status === 'archived' ? (
              <Button variant="secondary" onClick={() => act.mutate('restore')}>
                Restore
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => act.mutate('archive')}>
                Archive
              </Button>
            )}
          </div>
        }
      />
      <div className="space-y-6">
        <Details key={t.id} template={t} />
        {versions.isPending ? (
          <LoadingState />
        ) : (
          <Editor key={versions.data?.data[0]?.id ?? 'new'} template={t} start={versions.data?.data[0] ?? t.current_version} onSaved={refresh} />
        )}
        <Card title="Version history">
          {versions.data?.data.length ? (
            <ul className="divide-y divide-border">
              {versions.data.data.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    Version {v.version_number} {v.change_note && <span className="text-muted">— {v.change_note}</span>}
                  </span>
                  <span className="text-muted">{v.published_at ? `Published ${formatDateTime(v.published_at)}` : 'Draft'}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted">No versions yet. Save a draft, then publish it.</p>
          )}
        </Card>
      </div>
    </>
  )
}
