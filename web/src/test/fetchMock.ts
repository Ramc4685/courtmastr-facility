import { vi } from 'vitest'

export type Call = { method: string; url: string; headers: Record<string, string>; body: unknown }
type Handler = (call: Call) => { status: number; body?: unknown } | undefined

/** Routes fetch calls to handlers keyed by "METHOD /path" (query string ignored) and records every call. */
export function mockFetch(routes: Record<string, Handler | { status: number; body?: unknown }>) {
  const calls: Call[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = (init.method ?? 'GET').toUpperCase()
    const call: Call = { method, url, headers: (init.headers ?? {}) as Record<string, string>, body: init.body ? JSON.parse(String(init.body)) : undefined }
    calls.push(call)
    const route = routes[`${method} ${url.split('?')[0]}`]
    const out = typeof route === 'function' ? route(call) : route
    if (!out) return new Response(JSON.stringify({ status: 404, code: 'not-found' }), { status: 404 })
    return new Response(out.body === undefined ? null : JSON.stringify(out.body), {
      status: out.status,
      headers: { 'content-type': out.status >= 400 ? 'application/problem+json' : 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fn)
  return calls
}
