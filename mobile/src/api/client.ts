// Typed client generated from backend/openapi.json (`pnpm gen:api`). Every call goes through `send`, which
// adds the tenant and bearer token, retries once after a refresh on 401, and turns failures into ApiError.
import createClient from 'openapi-fetch';

import { tenantBase } from '../lib/config';
import { accessToken, activeSlug, refreshSession } from '../lib/session';
import { ApiError, networkError, problemFrom } from './errors';
import type { paths } from './schema';

function requireSlug(): string {
  const slug = activeSlug();
  if (!slug) throw new ApiError({ status: 400, code: 'no-tenant', detail: 'Choose a facility first.' });
  return slug;
}

async function attempt(request: Request, token: string | null): Promise<Response> {
  const { headers } = tenantBase(requireSlug());
  const out = new Request(request);
  Object.entries(headers).forEach(([name, value]) => out.headers.set(name, value));
  if (token) out.headers.set('Authorization', `Bearer ${token}`);
  try {
    return await fetch(out);
  } catch (cause) {
    throw networkError(cause);
  }
}

export async function send(request: Request): Promise<Response> {
  const retry = request.clone();
  const token = await accessToken();
  const response = await attempt(request, token);
  if (response.status !== 401 || !token) return response;
  const renewed = await refreshSession();
  return renewed ? attempt(retry, renewed.access) : response;
}

let clients: Record<string, ReturnType<typeof createClient<paths>>> = {};

/** The typed client for the active tenant. */
export function api() {
  const slug = requireSlug();
  clients[slug] ??= createClient<paths>({ baseUrl: tenantBase(slug).baseUrl, fetch: send });
  return clients[slug];
}

export const resetClients = () => {
  clients = {};
};

/** Throw ApiError for any non-2xx result from the typed client. */
export async function unwrap<T>(result: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await result;
  if (response.ok) return data as T;
  const body = (error ?? {}) as Record<string, unknown>;
  throw new ApiError({
    ...body,
    status: response.status,
    code: typeof body.code === 'string' ? body.code : `http-${response.status}`,
  });
}

type RawOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  idempotencyKey?: string;
};

/** For planned endpoints that are not in backend/openapi.json yet (src/adapters/api.ts only). */
export async function raw<T>(path: string, { method = 'GET', query, body, idempotencyKey }: RawOptions = {}): Promise<T> {
  const { baseUrl } = tenantBase(requireSlug());
  const qs = Object.entries(query ?? {})
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  const response = await send(
    new Request(`${baseUrl}/api/v1${path}${qs ? `?${qs}` : ''}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
  if (!response.ok) throw await problemFrom(response);
  return (response.status === 204 ? undefined : await response.json()) as T;
}
