import { useState, type ChangeEvent } from 'react'
import { ApiError, uploadFile } from '../api/client'
import type { paths } from '../api/schema'
import { Input } from './Field'

type Props<T> = {
  label: string
  /** The stored_file purpose the route files this under; names the input. The server enforces the real policy. */
  purpose: string
  /** Accepted MIME types, e.g. ['image/jpeg', 'image/png']. */
  accept: string[]
  maxBytes: number
  /** The context's upload route (raw bytes, PUT) and its path parameters. */
  route: keyof paths
  path?: Record<string, string>
  hint?: string
  /** The upload route's method; most replace a file (PUT), a gallery adds one (POST). */
  method?: 'PUT' | 'POST'
  onUploaded: (result: T) => void
}

const size = (bytes: number) => (bytes >= 2 ** 20 ? `${Math.round(bytes / 2 ** 20)} MB` : `${Math.round(bytes / 1024)} KB`)

/** One accessible file picker: checks type and size before sending (a courtesy; the server re-checks), uploads
 * through the API client, and announces progress and errors to assistive technology. */
export function FileUpload<T>({ label, purpose, accept, maxBytes, route, path = {}, hint, method = 'PUT', onUploaded }: Props<T>) {
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  async function onChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = '' // picking the same file again fires change again
    if (!file) return
    if (!accept.includes(file.type)) return setError(`Choose a file of type ${accept.join(', ')}.`)
    if (file.size > maxBytes) return setError(`Files may not exceed ${size(maxBytes)}.`)
    setError(undefined)
    setBusy(true)
    try {
      onUploaded(await uploadFile<T>(route, path, file, method))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The upload failed. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <Input
        type="file"
        label={label}
        name={purpose}
        accept={accept.join(',')}
        hint={hint ?? `Up to ${size(maxBytes)}.`}
        error={error}
        disabled={busy}
        aria-busy={busy || undefined}
        onChange={onChange}
        className="[&_input]:py-2 [&_input]:h-auto"
      />
      <p role="status" className="sr-only">
        {busy ? 'Uploading…' : ''}
      </p>
    </div>
  )
}
