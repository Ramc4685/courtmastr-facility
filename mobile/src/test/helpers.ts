/** A fetch double that records requests and answers from a list of handlers in order. */
export type Call = { url: string; method: string; headers: Record<string, string>; body: unknown };

export function mockFetch(handlers: ((call: Call) => Response | Promise<Response>)[]) {
  const calls: Call[] = [];
  const fn = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init);
    const text = await req.clone().text();
    const headers: Record<string, string> = {};
    req.headers.forEach((v, k) => (headers[k] = v));
    const call = { url: req.url, method: req.method, headers, body: text ? JSON.parse(text) : undefined };
    calls.push(call);
    const handler = handlers.shift();
    if (!handler) throw new Error(`unexpected fetch ${call.method} ${call.url}`);
    return handler(call);
  });
  globalThis.fetch = fn as unknown as typeof fetch;
  return calls;
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': status >= 400 ? 'application/problem+json' : 'application/json' } });

export function grant(overrides: Record<string, unknown> = {}) {
  return {
    id: 's1',
    kind: 'mobile',
    principal: { kind: 'client', identity_id: 'i1', email: 'member@example.com', display_name: 'member@example.com', client_ids: [] },
    access_token: 'fhs_access_1',
    refresh_token: 'fhr_refresh_1',
    access_expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
    idle_expires_at: new Date(Date.now() + 90 * 86_400_000).toISOString(),
    absolute_expires_at: new Date(Date.now() + 400 * 86_400_000).toISOString(),
    mfa_required: false,
    ...overrides,
  };
}
