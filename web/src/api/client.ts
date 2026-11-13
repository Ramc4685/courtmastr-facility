/**
 * Thin fetch wrapper over the generated OpenAPI types (security-baseline 5.3, overview 3.12/3.13).
 * - One HttpOnly cookie carries the session; its CSRF token is kept in memory only and sent on every non-GET.
 * - The anonymous auth POSTs (sign-in, emailed links, link consumption) send the pre-session token instead
 *   (login CSRF), fetched once from GET /auth/pre-session and fetched again if the server refuses it.
 * - Every mutation carries an Idempotency-Key, reused on that one retry.
 * - Non-2xx responses become ApiError with the problem+json body; a 401 means the session is over.
 * - A 403 `step-up-required` (a `+` permission, ADR 0002 section 4) asks the registered handler to confirm the
 *   user once (one shared prompt for concurrent requests), then retries the original request once.
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
let preToken: Promise<string | null> | null = null
/** Set on sign-in and session restore, cleared on sign-out; either way the pre-session token is re-fetched. */
export const setCsrfToken = (token: string | null | undefined) => {
  csrfToken = token ?? null
  preToken = null
}

let onUnauthenticated: () => void = () => {}
export const setUnauthenticatedHandler = (fn: () => void) => {
  onUnauthenticated = fn
}

/** Resolves true once the user has re-authenticated (the session and CSRF token have rotated), false if they gave up. */
let onStepUp: (() => Promise<boolean>) | null = null
let stepUpPrompt: Promise<boolean> | null = null
export const setStepUpHandler = (fn: (() => Promise<boolean>) | null) => {
  onStepUp = fn
}
function confirmIdentity(): Promise<boolean> {
  stepUpPrompt ??= (onStepUp ? onStepUp() : Promise.resolve(false)).finally(() => {
    stepUpPrompt = null
  })
  return stepUpPrompt
}

// Anonymous routes find the tenant from the host; where the host carries no tenant (local development on
// localhost) the slug is sent as a header. It is an address, not a credential.
const TENANT_SLUG: string | undefined =
  import.meta.env.VITE_TENANT_SLUG ?? (import.meta.env.DEV || import.meta.env.MODE === 'test' ? 'courtside-demo' : undefined)

// Anonymous auth endpoints guarded by the pre-session token (security-baseline 5.3 item 4).
const PRE_SESSION = [
  '/api/v1/auth/sign-in', '/api/v1/auth/magic-links', '/api/v1/auth/password-resets', '/api/v1/auth/magic-links/consume',
  '/api/v1/auth/password-resets/consume', '/api/v1/auth/invitations/accept', '/api/v1/auth/mfa/enrolment',
  '/api/v1/auth/mfa/verify', '/api/v1/auth/oidc/authorize', '/api/v1/auth/oidc/callback', '/api/v1/auth/oidc/link',
]
// A 401 from these is an answer, not an expired session. Kiosk routes use the device's kiosk cookie.
const NOT_SESSION = [...PRE_SESSION, '/api/v1/kiosk/pair', '/api/v1/kiosk/config', '/api/v1/kiosk/lookups', '/api/v1/kiosk/check-ins', '/api/v1/kiosk/exit']

type Options = { path?: Record<string, string>; query?: Record<string, string | number | boolean | null | undefined>; body?: unknown; idempotencyKey?: string }

function buildUrl(template: string, opts: Options): string {
  const path = template.replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(opts.path?.[k] ?? ''))
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  const q = qs.toString()
  return q ? `${path}?${q}` : path
}

/** The pre-session token, shared by concurrent callers; null when it cannot be had (the server then refuses). */
function preSessionToken(): Promise<string | null> {
  preToken ??= fetch('/api/v1/auth/pre-session', { credentials: 'same-origin', headers: { accept: 'application/json' } })
    .then(async (res) => (res.ok ? ((await res.json()) as Schemas['PreSessionOut']).csrf_token : null))
    .catch(() => null)
  return preToken
}

/** A fresh pre-session pair, not the cached one: a signed-in round trip that ends at a guarded route (OIDC
 * step-up ends at the callback) needs the cookie live for the whole trip, and the GET also renews its Max-Age. */
export function refreshPreSession(): Promise<string | null> {
  preToken = null
  return preSessionToken()
}

const refusedWith = async (res: Response, code: string) =>
  res.status === 403 && ((await res.clone().json().catch(() => ({}))) as Problem).code === code

export async function request<T>(method: Method, template: string, opts: Options = {}): Promise<T> {
  const url = buildUrl(template, opts)
  const headers: Record<string, string> = { accept: 'application/json' }
  if (opts.body !== undefined) headers['content-type'] = 'application/json'
  if (TENANT_SLUG) headers['x-tenant-slug'] = TENANT_SLUG
  // A caller that may retry one user action across requests (taking a payment) passes its own stable key.
  if (method !== 'get') headers['idempotency-key'] = opts.idempotencyKey ?? crypto.randomUUID()

  const guarded = PRE_SESSION.includes(template)
  const send = async () => {
    const token = guarded ? await preSessionToken() : csrfToken
    return fetch(url, {
      method: method.toUpperCase(),
      headers: method !== 'get' && token ? { ...headers, 'x-csrf-token': token } : headers,
      credentials: 'same-origin',
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    })
  }

  let res = await send()
  if (guarded && (await refusedWith(res, 'csrf-failed'))) {
    preToken = null // the pre-session cookie lapsed: take a fresh pair and retry once
    res = await send()
  }
  if (template !== '/api/v1/auth/step-up' && (await refusedWith(res, 'step-up-required')) && (await confirmIdentity())) {
    res = await send() // same Idempotency-Key: the refused attempt released its claim
  }
  if (res.status === 401 && !NOT_SESSION.includes(template)) onUnauthenticated()
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

/** PUT (or POST) raw file bytes to an upload route (paper scans, client photos, note attachments, import sources).
 * Same CSRF, idempotency, step-up and problem handling as `request`; no refresh retry. A File is re-readable, so
 * the step-up retry can send it again. */
export async function uploadFile<T>(template: keyof paths, path: Record<string, string>, file: File, method: 'PUT' | 'POST' = 'PUT'): Promise<T> {
  const headers: Record<string, string> = {
    accept: 'application/json',
    'content-type': file.type || 'application/octet-stream',
    'x-file-name': encodeURIComponent(file.name).slice(0, 200),
    'idempotency-key': crypto.randomUUID(),
  }
  if (TENANT_SLUG) headers['x-tenant-slug'] = TENANT_SLUG
  if (csrfToken) headers['x-csrf-token'] = csrfToken
  const send = () => fetch(buildUrl(template as string, { path }), { method, headers, credentials: 'same-origin', body: file })
  let res = await send()
  if ((await refusedWith(res, 'step-up-required')) && (await confirmIdentity())) res = await send()
  const data: unknown = await res.json().catch(() => undefined)
  if (!res.ok) throw new ApiError({ ...((data ?? {}) as Problem), status: res.status })
  return data as T
}

/** GET (or POST, for an export that audits) a file route and hand the browser the attachment (signed PDFs,
 * paper copies, CSV exports). */
export async function downloadFile(template: keyof paths, opts: Options, fallbackName: string, method: 'GET' | 'POST' = 'GET'): Promise<void> {
  const headers: Record<string, string> = {}
  if (TENANT_SLUG) headers['x-tenant-slug'] = TENANT_SLUG
  if (method === 'POST') {
    headers['idempotency-key'] = crypto.randomUUID()
    if (csrfToken) headers['x-csrf-token'] = csrfToken
  }
  const res = await fetch(buildUrl(template as string, opts), { method, headers, credentials: 'same-origin' })
  if (res.status === 401) onUnauthenticated()
  if (!res.ok) throw new ApiError({ ...(((await res.json().catch(() => ({}))) ?? {}) as Problem), status: res.status })
  const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const link = Object.assign(document.createElement('a'), { href: url, download: name })
  link.click()
  URL.revokeObjectURL(url)
}
