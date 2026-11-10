import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

export function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-3 py-12 text-muted">
      <Spinner />
      <span>{label}…</span>
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <svg viewBox="0 0 48 32" className="h-10 w-14 text-border" aria-hidden="true">
        <rect x="2" y="2" width="44" height="28" rx="3" fill="none" stroke="currentColor" strokeWidth="2.5" />
        <path d="M24 2v28M2 16h7M39 16h7" stroke="currentColor" strokeWidth="2.5" />
      </svg>
      <p className="font-medium">{title}</p>
      {children && <p className="max-w-sm text-muted">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** Explains an error in words a staff member can act on; 403 gets its own message (still possible when
 * navigation hides the entry, e.g. the role changed in another tab). */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const forbidden = error instanceof ApiError && error.status === 403
  const title = forbidden ? 'You do not have access to this' : 'Something went wrong'
  const detail = forbidden
    ? 'Your role does not include this permission. Ask an administrator if you need it.'
    : error instanceof Error
      ? error.message
      : 'Please try again.'
  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center gap-2 px-6 py-12 text-center">
      <p className="font-medium">{title}</p>
      <p className="text-muted">{detail}</p>
      {error instanceof ApiError && error.problem.trace_id && <p className="text-xs text-muted">Reference: {error.problem.trace_id}</p>}
      {onRetry && !forbidden && (
        <button type="button" onClick={onRetry} className="mt-2 font-medium text-primary underline-offset-2 hover:underline">
          Try again
        </button>
      )}
    </div>
  )
}
