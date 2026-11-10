import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { api, type Schemas } from '../../api/client'
import { fullName } from '../../lib/format'
import { useDebounced } from '../../lib/useDebounced'

export type ClientSummary = Schemas['ClientListItem']
type Props = {
  label: string
  value: ClientSummary | null
  onChange: (client: ClientSummary | null) => void
  hint?: string
  error?: string
  required?: boolean
  disabled?: boolean
}

const detail = (c: ClientSummary) => [c.member_number, c.primary_email, c.phone_mobile].filter(Boolean).join(' · ')

/** Pick one active client by name, email, phone or member number. A WAI-ARIA combobox with a listbox popup:
 * type to search, arrow keys to move, Enter to choose, Escape to close. Any screen that needs "which client?"
 * (booking, sale, payment) uses this; it needs `clients.client.read`. */
export function ClientPicker({ label, value, onChange, hint, error, required, disabled }: Props) {
  const id = useId()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const q = useDebounced(text.trim(), 250)
  const search = useQuery({
    queryKey: ['clients', 'picker', q],
    queryFn: () => api.get('/api/v1/clients', { query: { q, status: 'active', limit: 8 } }),
    enabled: open && q.length >= 2,
  })
  const options = q.length >= 2 ? (search.data?.data ?? []) : []
  const status =
    q.length < 2 ? 'Type at least 2 characters to search.' : search.isPending ? 'Searching…' : search.isError ? 'Search failed. Try again.' : options.length === 0 ? 'No clients match.' : `${options.length} ${options.length === 1 ? 'client' : 'clients'} found.`
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined

  // Choosing swaps the input for the summary (and back), so focus is handed to the control that replaces it.
  const inputRef = useRef<HTMLInputElement>(null)
  const changeRef = useRef<HTMLButtonElement>(null)
  const moveFocus = useRef(false)
  useEffect(() => {
    if (!moveFocus.current) return
    moveFocus.current = false
    ;(value ? changeRef : inputRef).current?.focus()
  }, [value])

  const choose = (client: ClientSummary) => {
    moveFocus.current = true
    onChange(client)
    setText('')
    setOpen(false)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setOpen(true)
      if (options.length) setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length)
    } else if (e.key === 'Enter' && open && options[active]) {
      e.preventDefault() // choose, do not submit the surrounding form
      choose(options[active])
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation() // close the list, not the dialog around it
      setOpen(false)
    }
  }

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} id={`${id}-label`} className="block text-sm font-medium">
        {label}
      </label>
      {value ? (
        <div role="group" aria-labelledby={`${id}-label`} className="flex h-10 items-center justify-between gap-2 rounded border border-border bg-surface-2 px-3 text-sm">
          <span className="truncate">
            <span className="font-medium">{fullName(value)}</span>
            {detail(value) && <span className="text-muted"> · {detail(value)}</span>}
          </span>
          <button
            ref={changeRef}
            type="button"
            disabled={disabled}
            className="shrink-0 font-medium text-primary underline-offset-2 hover:underline"
            aria-label={`Change client, currently ${fullName(value)}`}
            aria-describedby={describedBy}
            onClick={() => {
              moveFocus.current = true
              onChange(null)
            }}
          >
            Change
          </button>
        </div>
      ) : (
        <div className="relative">
          <input
            ref={inputRef}
            id={id}
            type="text"
            role="combobox"
            aria-expanded={open}
            aria-controls={`${id}-list`}
            aria-autocomplete="list"
            aria-activedescendant={open && options[active] ? `${id}-option-${active}` : undefined}
            aria-describedby={describedBy}
            aria-invalid={error ? true : undefined}
            aria-required={required}
            autoComplete="off"
            disabled={disabled}
            placeholder="Name, email, phone or member number"
            className="block h-10 w-full rounded border border-border bg-surface px-3 text-sm text-fg placeholder:text-muted disabled:bg-surface-2 disabled:text-muted aria-[invalid=true]:border-danger"
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setActive(0)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setOpen(false)}
            onKeyDown={onKeyDown}
          />
          <ul
            id={`${id}-list`}
            role="listbox"
            aria-label={`${label}: matching clients`}
            hidden={!open || options.length === 0}
            className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded border border-border bg-surface py-1 shadow-card"
          >
            {options.map((client, index) => (
              // mousedown, not click: it fires before the input's blur closes the list. Keyboard users choose with Enter.
              <li
                key={client.id}
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={index === active}
                className={`cursor-pointer px-3 py-2 text-sm ${index === active ? 'bg-surface-2' : ''}`}
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(client)
                }}
                onMouseEnter={() => setActive(index)}
              >
                <span className="font-medium">{fullName(client)}</span>
                {detail(client) && <span className="block text-xs text-muted">{detail(client)}</span>}
              </li>
            ))}
          </ul>
          <p role="status" className={open ? 'mt-1 text-xs text-muted' : 'sr-only'}>
            {open ? status : ''}
          </p>
        </div>
      )}
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-danger">
          {error}
        </p>
      )}
    </div>
  )
}
