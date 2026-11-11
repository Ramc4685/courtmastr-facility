import type { Schemas } from '../../api/client'
import { Checkbox, Input, Select } from '../../components/Field'
import { weekday } from './time'

export type Rule = Schemas['RecurrenceRule']
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const UNIT: Record<string, string> = { daily: 'days', weekly: 'weeks', monthly_by_date: 'months', monthly_by_weekday: 'months', yearly: 'years' }

/** A sensible starting rule for a booking on `date`: weekly on that weekday, ten times. */
export const defaultRule = (date: string): Rule => ({ pattern: 'weekly', interval_count: 1, weekdays: [weekday(date)], range_type: 'count', occurrence_limit: 10, month_week: null, until_on: null })

/** The rule as words, for the preview heading and screen readers. */
export function describeRule(rule: Rule): string {
  const every = rule.interval_count > 1 ? `every ${rule.interval_count} ${UNIT[rule.pattern]}` : { daily: 'every day', weekly: 'every week', monthly_by_date: 'every month', monthly_by_weekday: 'every month', yearly: 'every year', single: 'once' }[rule.pattern]
  const days = rule.pattern === 'weekly' && rule.weekdays?.length ? ` on ${rule.weekdays.map((d) => DAYS[d - 1]).join(', ')}` : ''
  const nth = rule.pattern === 'monthly_by_weekday' && rule.month_week && rule.weekdays?.[0] ? ` on the ${rule.month_week === -1 ? 'last' : ['first', 'second', 'third', 'fourth', 'fifth'][rule.month_week - 1]} ${DAYS[rule.weekdays[0] - 1]}` : ''
  const end = rule.range_type === 'count' ? `, ${rule.occurrence_limit ?? 0} times` : rule.until_on ? `, until ${rule.until_on}` : ''
  return `Repeats ${every}${days}${nth}${end}`
}

export function RecurrenceEditor({ rule, date, onChange, errors }: { rule: Rule; date: string; onChange: (rule: Rule) => void; errors: Record<string, string> }) {
  const set = (patch: Partial<Rule>) => onChange({ ...rule, ...patch })
  const err = (k: string) => errors[`recurrence/${k}`]
  return (
    <fieldset className="grid gap-3 rounded border border-border p-3 sm:grid-cols-2">
      <legend className="px-1 text-sm font-medium">Repeat</legend>
      <Select
        label="Pattern"
        value={rule.pattern}
        error={err('pattern')}
        onChange={(e) => {
          const pattern = e.target.value as Rule['pattern']
          set({
            pattern,
            weekdays: pattern === 'weekly' || pattern === 'monthly_by_weekday' ? [weekday(date)] : null,
            month_week: pattern === 'monthly_by_weekday' ? (Math.min(4, Math.ceil(Number(date.slice(8, 10)) / 7)) as Rule['month_week']) : null,
          })
        }}
        options={[
          { value: 'daily', label: 'Daily' },
          { value: 'weekly', label: 'Weekly' },
          { value: 'monthly_by_date', label: 'Monthly on the same date' },
          { value: 'monthly_by_weekday', label: 'Monthly on the same weekday' },
          { value: 'yearly', label: 'Yearly' },
        ]}
      />
      <Input label={`Every how many ${UNIT[rule.pattern] ?? 'times'}`} type="number" min={1} max={52} value={String(rule.interval_count)} error={err('interval_count')} onChange={(e) => set({ interval_count: Number(e.target.value) })} />
      {rule.pattern === 'weekly' && (
        <fieldset className="sm:col-span-2">
          <legend className="mb-1 text-sm font-medium">On</legend>
          <div className="flex flex-wrap gap-3">
            {DAYS.map((d, i) => (
              <Checkbox
                key={d}
                label={d.slice(0, 3)}
                aria-label={d}
                checked={rule.weekdays?.includes(i + 1) ?? false}
                onChange={(e) => set({ weekdays: e.target.checked ? [...(rule.weekdays ?? []), i + 1].sort() : (rule.weekdays ?? []).filter((x) => x !== i + 1) })}
              />
            ))}
          </div>
          {err('weekdays') && <p className="mt-1 text-xs font-medium text-danger">{err('weekdays')}</p>}
        </fieldset>
      )}
      {rule.pattern === 'monthly_by_weekday' && (
        <>
          <Select
            label="Week of the month"
            value={String(rule.month_week ?? 1)}
            error={err('month_week')}
            onChange={(e) => set({ month_week: Number(e.target.value) as Rule['month_week'] })}
            options={[
              { value: '1', label: 'First' },
              { value: '2', label: 'Second' },
              { value: '3', label: 'Third' },
              { value: '4', label: 'Fourth' },
              { value: '-1', label: 'Last' },
            ]}
          />
          <Select label="Weekday" value={String(rule.weekdays?.[0] ?? 1)} onChange={(e) => set({ weekdays: [Number(e.target.value)] })} options={DAYS.map((d, i) => ({ value: String(i + 1), label: d }))} />
        </>
      )}
      <Select
        label="Ends"
        value={rule.range_type}
        onChange={(e) => set(e.target.value === 'count' ? { range_type: 'count', occurrence_limit: rule.occurrence_limit ?? 10, until_on: null } : { range_type: 'until', until_on: rule.until_on ?? date, occurrence_limit: null })}
        options={[
          { value: 'count', label: 'After a number of times' },
          { value: 'until', label: 'On a date' },
        ]}
      />
      {rule.range_type === 'count' ? (
        <Input label="Number of times" type="number" min={1} max={2000} value={String(rule.occurrence_limit ?? '')} error={err('occurrence_limit')} onChange={(e) => set({ occurrence_limit: Number(e.target.value) })} />
      ) : (
        <Input label="Last date" type="date" min={date} value={rule.until_on ?? ''} error={err('until_on')} onChange={(e) => set({ until_on: e.target.value })} />
      )}
      <p className="text-xs text-muted sm:col-span-2" aria-live="polite">
        {describeRule(rule)}.
      </p>
    </fieldset>
  )
}
