import { useEffect, type ReactNode } from 'react'
import { BrandMark } from '../../components/Icon'
import { APP_NAME } from '../../lib/format'

export function AuthLayout({ title, children }: { title: string; children: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`
  }, [title])
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div aria-hidden="true" className="relative hidden overflow-hidden bg-rail lg:block">
        {/* court lines */}
        <svg className="absolute inset-0 h-full w-full text-rail-active" viewBox="0 0 400 600" preserveAspectRatio="xMidYMid slice">
          <g fill="none" stroke="currentColor" strokeWidth="3">
            <rect x="40" y="60" width="320" height="480" />
            <path d="M40 300h320M200 60v480M40 180h320M40 420h320" />
            <circle cx="200" cy="300" r="46" />
          </g>
          <circle cx="282" cy="214" r="9" fill="rgb(var(--accent))" />
        </svg>
        <div className="absolute bottom-10 left-10 right-10 text-rail-fg">
          <p className="text-3xl font-semibold tracking-tight">Run every court, class and member from one place.</p>
        </div>
      </div>
      <main className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3">
            <BrandMark className="h-10 w-10" />
            <span className="text-lg font-semibold">{APP_NAME}</span>
          </div>
          <h1 className="mb-6">{title}</h1>
          {children}
        </div>
      </main>
    </div>
  )
}

/** Only same-app paths are honoured, so a crafted link cannot bounce the user to another site. */
// Pin to our own origin: prefix checks alone miss "/\evil.com" style redirects.
export const safeNext = (next: string | null) => {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/'
  try {
    const u = new URL(next, window.location.origin)
    return u.origin === window.location.origin ? u.pathname + u.search + u.hash : '/'
  } catch {
    return '/'
  }
}
