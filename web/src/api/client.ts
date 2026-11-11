/**
 * Thin fetch wrapper over the generated OpenAPI types (security-baseline 5.3, overview 3.12/3.13).
 * - Cookies carry the session (HttpOnly); the CSRF token is kept in memory only and sent on every non-GET.
 * - Every mutation carries an Idempotency-Key, reused on the one retry after a token refresh.
 * - Non-2xx responses become ApiError with the problem+json body.
 * - A 401 triggers one shared POST /auth/refresh, then the request is retried once.
 */
import type { components, paths } from './schema'

export type Schemas = components['schemas']
type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'
type Op<P extends keyof paths, M extends Method> = NonNullable<paths[P][M]>
type Json<T> = T extends { content: { 'application/json': infer B } } ? B : never
type Body<O> = O extends { requestBody: infer R } ? Json<R> : O extends { requestBody?: infer R } ? Json<R> : never
type Ok<O> = O extends { responses: infer R }
  ? R extends { 200: infer X }
    ? Json<X>
    : R extends { 201: infer X }
      ? Json<X>
      : R extends { 202: infer X }
        ? Json<X>
        : undefined
  : never
type PathParams<O> = O extends { parameters: { path: infer PP } } ? PP : never

export type Problem = {
  type?: string
  title?: string
  status: number
  detail?: string
  code?: string
  trace_id?: string
  errors?: { pointer: string; code: string; detail: string }[]
  [extra: string]: unknown
}

export class ApiError extends Error {
  constructor(public problem: Problem) {
    super(problem.detail ?? problem.title ?? `Request failed (${problem.status})`)
    this.name = 'ApiError'
  }
  get status() {
    return this.problem.status
  }
  get code() {
    return this.problem.code
  }
}

/** Field errors keyed by JSON Pointer without the leading slash ("/name" -> "name"). */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {}
  return Object.fromEntries((error.problem.errors ?? []).map((e) => [e.pointer.replace(/^\//, ''), e.detail]))
}

let csrfToken: string | null = null
export const setCsrfToken = (token: string | null | undefined) => {
  csrfToken = token ?? null
}

let onUnauthenticated: () => void = () => {}
export const setUnauthenticatedHandler = (fn: () => void) => {
  onUnauthenticated = fn
}

// Anonymous routes find the tenant from the host; where the host carries no tenant (local development on
// localhost) the slug is sent as a header. It is an address, not a credential.
const TENANT_SLUG: string | undefined =
  import.meta.env.VITE_TENANT_SLUG ?? (import.meta.env.DEV || import.meta.env.MODE === 'test' ? 'courtside-demo' : undefined)

// Anonymous auth endpoints: a 401 there is an answer, not an expired session.
const NO_REFRESH = ['/api/v1/auth/sign-in', '/api/v1/auth/refresh', '/api/v1/auth/magic-links/consume']
// Kiosk routes authenticate with the device's kiosk cookie, never a staff session.
NO_REFRESH.push('/api/v1/kiosk/pair', '/api/v1/kiosk/config', '/api/v1/kiosk/lookups', '/api/v1/kiosk/check-ins', '/api/v1/kiosk/exit')

type Options = { path?: Record<string, string>; query?: Record<string, string | number | boolean | null | undefined>; body?: unknown; idempotencyKey?: string }

function buildUrl(template: string, opts: Options): string {
  const path = template.replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(opts.path?.[k] ?? ''))
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  const q = qs.toString()
  return q ? `${path}?${q}` : path
}

let refreshing: Promise<boolean> | null = null
function refresh(): Promise<boolean> {
  refreshing ??= fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'same-origin', headers: { accept: 'application/json' } })
    .then(async (res) => {
      if (!res.ok) return false
      setCsrfToken(((await res.json()) as Schemas['AuthSessionOut']).csrf_token)
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

export async function request<T>(method: Method, template: string, opts: Options = {}): Promise<T> {
  const url = buildUrl(template, opts)
  const headers: Record<string, string> = { accept: 'application/json' }
  if (opts.body !== undefined) headers['content-type'] = 'application/json'
  if (TENANT_SLUG) headers['x-tenant-slug'] = TENANT_SLUG
  // A caller that may retry one user action across requests (taking a payment) passes its own stable key.
  if (method !== 'get') headers['idempotency-key'] = opts.idempotencyKey ?? crypto.randomUUID()

  const send = () => {
    if (method !== 'get' && csrfToken) headers['x-csrf-token'] = csrfToken
    return fetch(url, {
      method: method.toUpperCase(),
      headers,
      credentials: 'same-origin',
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    })
  }

  let res = await send()
  if (res.status === 401 && !NO_REFRESH.includes(template)) {
    if (await refresh()) res = await send()
    if (res.status === 401) onUnauthenticated()
  }
  // 202 may carry a body (a long booking series answers with its status_url); an empty one parses to undefined.
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data: unknown = text ? JSON.parse(text) : undefined
  if (!res.ok) {
    const problem = (data && typeof data === 'object' ? data : {}) as Problem
    throw new ApiError({ ...problem, status: res.status })
  }
  return data as T
}

/** Typed entry points: paths, path params and bodies are checked against the generated schema. */
export const api = {
  get: <P extends keyof paths>(path: P, opts?: { path?: PathParams<Op<P, 'get'>>; query?: Options['query'] }) =>
    request<Ok<Op<P, 'get'>>>('get', path as string, opts as Options),
  post: <P extends keyof paths>(path: P, opts?: { path?: PathParams<Op<P, 'post'>>; body?: Body<Op<P, 'post'>>; idempotencyKey?: string }) =>
    request<Ok<Op<P, 'post'>>>('post', path as string, opts as Options),
  put: <P extends keyof paths>(path: P, opts: { path?: PathParams<Op<P, 'put'>>; query?: Options['query']; body: Body<Op<P, 'put'>> }) =>
    request<Ok<Op<P, 'put'>>>('put', path as string, opts as Options),
  patch: <P extends keyof paths>(path: P, opts: { path?: PathParams<Op<P, 'patch'>>; body: Body<Op<P, 'patch'>> }) =>
    request<Ok<Op<P, 'patch'>>>('patch', path as string, opts as Options),
  delete: <P extends keyof paths>(path: P, opts?: { path?: PathParams<Op<P, 'delete'>>; query?: Options['query'] }) =>
    request<Ok<Op<P, 'delete'>>>('delete', path as string, opts as Options),
}

/** PUT (or POST) raw file bytes to an upload route (paper scans, client photos, note attachments). Same CSRF,
 * idempotency and problem handling as `request`; no refresh retry, since the body stream is consumed. */
export async function uploadFile<T>(template: keyof paths, path: Record<string, string>, file: File, method: 'PUT' | 'POST' = 'PUT'): Promise<T> {
  const headers: Record<string, string> = {
    accept: 'application/json',
    'content-type': file.type || 'application/octet-stream',
    'x-file-name': encodeURIComponent(file.name).slice(0, 200),
    'idempotency-key': crypto.randomUUID(),
  }
  if (TENANT_SLUG) headers['x-tenant-slug'] = TENANT_SLUG
  if (csrfToken) headers['x-csrf-token'] = csrfToken
  const res = await fetch(buildUrl(template as string, { path }), { method, headers, credentials: 'same-origin', body: file })
  const data: unknown = await res.json().catch(() => undefined)
  if (!res.ok) throw new ApiError({ ...((data ?? {}) as Problem), status: res.status })
  return data as T
}

/** GET a file route and hand the browser the attachment (signed PDFs, paper copies). */
export async function downloadFile(template: keyof paths, opts: Options, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (TENANT_SLUG) headers['x-tenant-slug'] = TENANT_SLUG
  let res = await fetch(buildUrl(template as string, opts), { headers, credentials: 'same-origin' })
  if (res.status === 401 && (await refresh())) res = await fetch(buildUrl(template as string, opts), { headers, credentials: 'same-origin' })
  if (!res.ok) throw new ApiError({ ...(((await res.json().catch(() => ({}))) ?? {}) as Problem), status: res.status })
  const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const link = Object.assign(document.createElement('a'), { href: url, download: name })
  link.click()
  URL.revokeObjectURL(url)
}
