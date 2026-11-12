import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'

const control =
  'block w-full rounded border border-border bg-surface px-3 h-10 text-sm text-fg placeholder:text-muted disabled:bg-surface-2 disabled:text-muted aria-[invalid=true]:border-danger'

type FieldProps = { label: ReactNode; hint?: ReactNode; error?: string; className?: string }

/** Label, hint and error wired to the control with ids, aria-describedby and aria-invalid. */
function Field({ label, hint, error, className = '', children }: FieldProps & { children: (ids: { id: string; describedBy?: string }) => ReactNode }) {
  const id = useId()
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return (
    <div className={`space-y-1.5 ${className}`}>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children({ id, describedBy })}
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {/* Always mounted so an error that appears after submit is announced (WCAG 4.1.3); empty and out of flow until then. */}
      <p id={`${id}-error`} aria-live="polite" className={error ? 'text-xs font-medium text-danger' : 'sr-only'}>
        {error}
      </p>
    </div>
  )
}

export function Input({ label, hint, error, className, ...rest }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {({ id, describedBy }) => (
        <input id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} className={control} {...rest} />
      )}
    </Field>
  )
}

export type Option = { value: string; label: string }

export function Select({
  label,
  hint,
  error,
  className,
  options,
  placeholder,
  ...rest
}: FieldProps & SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; placeholder?: string }) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {({ id, describedBy }) => (
        <select id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} className={control} {...rest}>
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}

export function Checkbox({ label, hint, className = '', ...rest }: { label: ReactNode; hint?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId()
  return (
    <div className={`flex items-start gap-2 ${className}`}>
      <input id={id} type="checkbox" className="mt-0.5 h-4 w-4 rounded border-border accent-[rgb(var(--primary))]" aria-describedby={hint ? `${id}-hint` : undefined} {...rest} />
      <div>
        {/* The padding grows the click target to 24 px without moving anything (WCAG 2.5.8). */}
        <label htmlFor={id} className="-my-1 block py-1 text-sm">
          {label}
        </label>
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted">
            {hint}
          </p>
        )}
      </div>
    </div>
  )
}
