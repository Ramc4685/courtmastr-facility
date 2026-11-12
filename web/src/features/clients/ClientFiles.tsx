import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useRef, useState } from 'react'
import { api, downloadFile, uploadFile, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Card } from '../../components/PageHeader'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { fullName } from '../../lib/format'

/** Client photo (CLI-12) and note attachments (CLI-09). Staff screens only; the kiosk never shows photos. */

type Client = Schemas['ClientOut']
type Attachment = Schemas['NoteAttachmentOut']
// The upload routes sit under the API's 1 MiB body cap until Phase 8 widens it for them.
const MAX_HINT = 'up to 1 MB'

const sizes = { sm: 'h-8 w-8', md: 'h-16 w-16', lg: 'h-32 w-32' }

/** The photo bytes come from a permission-checked route; `v` changes with the file so a new photo shows at once. */
export function ClientPhoto({ clientId, photoFileId, name, size = 'md' }: { clientId: string; photoFileId?: string | null; name: string; size?: keyof typeof sizes }) {
  if (!photoFileId) return null
  return <img src={`/api/v1/clients/${clientId}/photo?v=${photoFileId}`} alt={name} className={`${sizes[size]} shrink-0 rounded-md border border-border bg-surface-2 object-cover`} />
}

/** For screens that only hold a client id (the check-in status card): loads the photo route itself and hides the
 * image when there is none (404) or the caller may not see it. Never reads the profile, which logs a recent view. */
export function ClientPhotoById({ clientId, name, size = 'md' }: { clientId: string; name: string; size?: keyof typeof sizes }) {
  const [failed, setFailed] = useState<string | null>(null)
  if (failed === clientId) return null
  return <img src={`/api/v1/clients/${clientId}/photo`} alt={name} onError={() => setFailed(clientId)} className={`${sizes[size]} shrink-0 rounded-md border border-border bg-surface-2 object-cover`} />
}

function FilePicker({ label, accept, busy, onFile }: { label: string; accept: string; busy: boolean; onFile: (file: File) => void }) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        ref={input}
        id={id}
        type="file"
        accept={accept}
        disabled={busy}
        className="block w-full text-sm"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFile(file)
          if (input.current) input.current.value = ''
        }}
      />
    </div>
  )
}

export function PhotoCard({ client }: { client: Client }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const editable = can('clients.client.update') && !client.merged_into_id && !client.erased_at
  const done = (message: string) => {
    toast('success', message)
    void qc.invalidateQueries({ queryKey: ['clients'] })
  }
  const upload = useMutation({
    mutationFn: (file: File) => uploadFile('/api/v1/clients/{client_id}/photo', { client_id: client.id }, file),
    onSuccess: () => done('Photo saved.'),
  })
  const remove = useMutation({
    mutationFn: () => api.delete('/api/v1/clients/{client_id}/photo', { path: { client_id: client.id } }),
    onSuccess: () => done('Photo removed.'),
  })
  if (!client.photo_file_id && !editable) return null
  return (
    <Card title="Photo">
      <div className="space-y-3">
        {client.photo_file_id ? <ClientPhoto clientId={client.id} photoFileId={client.photo_file_id} name={fullName(client)} size="lg" /> : <p className="text-sm text-muted">No photo yet.</p>}
        {editable && (
          <>
            <FilePicker label={`${client.photo_file_id ? 'Replace' : 'Upload'} photo (JPEG or PNG, ${MAX_HINT})`} accept="image/jpeg,image/png" busy={upload.isPending} onFile={(f) => upload.mutate(f)} />
            {client.photo_file_id && (
              <Button variant="secondary" size="sm" loading={remove.isPending} onClick={() => remove.mutate()}>
                Remove photo
              </Button>
            )}
          </>
        )}
        {(upload.error ?? remove.error) && <p className="text-sm text-danger">{(upload.error ?? remove.error)?.message}</p>}
      </div>
    </Card>
  )
}

export function NoteAttachments({ noteId }: { noteId: string }) {
  const qc = useQueryClient()
  const { can } = useAuth()
  const queryKey = ['client-notes', noteId, 'attachments']
  const list = useQuery({ queryKey, queryFn: () => api.get('/api/v1/client-notes/{note_id}/attachments', { path: { note_id: noteId } }) })
  const refresh = () => void qc.invalidateQueries({ queryKey })
  const upload = useMutation({
    mutationFn: (file: File) => uploadFile<Attachment>('/api/v1/client-notes/{note_id}/attachments', { note_id: noteId }, file, 'POST'),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/client-notes/{note_id}/attachments/{attachment_id}', { path: { note_id: noteId, attachment_id: id } }),
    onSuccess: refresh,
  })
  const items = list.data ?? []
  const writable = can('clients.activity.write')
  const error = upload.error ?? remove.error
  return (
    <div className="mt-2 space-y-2">
      {items.length > 0 && (
        <ul aria-label="Attachments" className="space-y-1">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void downloadFile('/api/v1/client-notes/{note_id}/attachments/{attachment_id}', { path: { note_id: noteId, attachment_id: a.id } }, a.file_name ?? 'attachment')}
              >
                Download {a.file_name ?? 'attachment'}
              </Button>
              <span className="text-xs text-muted">{Math.max(1, Math.round(a.size_bytes / 1024))} KB</span>
              {writable && (
                <Button variant="ghost" size="sm" aria-label={`Remove ${a.file_name ?? 'attachment'}`} loading={remove.isPending && remove.variables === a.id} onClick={() => remove.mutate(a.id)}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {writable && items.length < 5 && <FilePicker label={`Attach a file (PDF, JPEG or PNG, ${MAX_HINT})`} accept="application/pdf,image/jpeg,image/png" busy={upload.isPending} onFile={(f) => upload.mutate(f)} />}
      {error && <p className="text-sm text-danger">{error.message}</p>}
    </div>
  )
}
