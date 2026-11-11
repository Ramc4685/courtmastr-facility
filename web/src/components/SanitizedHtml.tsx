import DOMPurify from 'dompurify'
import { useMemo } from 'react'

// Mirrors the server allow-list (backend documents/domain/content.py, security-baseline 9.2). The server already
// sanitises on save; this second pass means a stored body can never run script in the staff app.
const ALLOWED_TAGS = ['h1', 'h2', 'h3', 'h4', 'p', 'br', 'hr', 'strong', 'b', 'em', 'i', 'u', 'blockquote', 'ul', 'ol', 'li', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td']
const ALLOWED_ATTR = ['href', 'title', 'colspan', 'rowspan', 'rel']
const ALLOWED_URI_REGEXP = /^(?:https:|mailto:|tel:)/i

export function sanitize(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR, ALLOWED_URI_REGEXP })
}

/** The only place the app renders stored rich text (ESLint bans dangerouslySetInnerHTML everywhere else). */
export function SanitizedHtml({ html, className = '' }: { html: string; className?: string }) {
  const clean = useMemo(() => sanitize(html), [html])
  return <div className={`rich-text ${className}`} dangerouslySetInnerHTML={{ __html: clean }} />
}
