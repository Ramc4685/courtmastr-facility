/** RFC 9457 problem+json as the API emits it (docs/architecture/overview.md 3.13). */
export type Problem = {
  type?: string;
  title?: string;
  status: number;
  code: string;
  detail?: string;
  errors?: { pointer?: string; code?: string; detail?: string }[];
  trace_id?: string;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title ?? problem.code);
    this.name = 'ApiError';
    this.status = problem.status;
    this.code = problem.code;
    this.problem = problem;
  }

  /** No response at all: offline, DNS, server down. */
  get isNetwork(): boolean {
    return this.status === 0;
  }
}

export const networkError = (cause: unknown) =>
  new ApiError({ status: 0, code: 'network', title: 'No connection', detail: String(cause) });

export async function problemFrom(response: Response): Promise<ApiError> {
  let body: Partial<Problem> = {};
  try {
    body = (await response.json()) as Partial<Problem>;
  } catch {
    // non-JSON error body: fall through with the status alone
  }
  return new ApiError({
    ...body,
    status: response.status,
    code: body.code ?? `http-${response.status}`,
    title: body.title ?? response.statusText,
  });
}

/** One sentence a member can act on. Field errors are shown next to fields by the caller. */
export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isNetwork) return 'You appear to be offline. Showing what was saved on this phone.';
    if (error.status === 404 && error.code === 'not-found') return 'This feature is not available yet.';
    return error.problem.detail ?? error.problem.title ?? 'Something went wrong.';
  }
  return 'Something went wrong.';
}
