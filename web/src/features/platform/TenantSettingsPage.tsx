import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { timeZoneOptions } from '../../lib/format'
import { BrandingCard } from './branding'
import { brandVars } from '../../lib/brandTheme'

/** Says up front when the portal will fall back to its own colour because this one fails WCAG AA contrast. */
function colourHint(value: string, kind: 'primary' | 'accent'): string {
  if (!value) return 'Blank uses the product colour. Format #RRGGBB.'
  const vars = kind === 'primary' ? brandVars(value, null) : brandVars(null, value)
  return Object.keys(vars).length ? 'Passes contrast checks.' : 'Too light for readable contrast: the portal will use the product colour instead.'
}

function SettingsForm({ tenant }: { tenant: Schemas['TenantOut'] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    name: tenant.name, default_time_zone: tenant.default_time_zone, currency: tenant.currency, locale: tenant.locale,
    brand_primary_color: tenant.brand_primary_color ?? '', brand_accent_color: tenant.brand_accent_color ?? '',
  })
  const save = useMutation({
    mutationFn: () => api.patch('/api/v1/tenant', { body: { ...form, brand_primary_color: form.brand_primary_color || null, brand_accent_color: form.brand_accent_color || null } }),
    onSuccess: (t) => {
      qc.setQueryData(['tenant'], t)
      void qc.invalidateQueries({ queryKey: ['session'] })
      toast('success', 'Settings saved.')
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Card title="Account profile" className="max-w-2xl">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger sm:col-span-2">
            {save.error.message}
          </p>
        )}
        <Input className="sm:col-span-2" label="Business name" value={form.name} error={errors.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Select
          label="Default time zone"
          hint="Used for new locations and account-wide reports."
          value={form.default_time_zone}
          error={errors.default_time_zone}
          options={timeZoneOptions(form.default_time_zone)}
          onChange={(e) => setForm({ ...form, default_time_zone: e.target.value })}
        />
        <Input label="Currency" hint="ISO code, e.g. USD" maxLength={3} value={form.currency} error={errors.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} />
        <Input label="Locale" hint="Formats dates and numbers, e.g. en-US" value={form.locale} error={errors.locale} onChange={(e) => setForm({ ...form, locale: e.target.value })} />
        <Input label="Portal main colour" placeholder="#0b6850" hint={colourHint(form.brand_primary_color, 'primary')} value={form.brand_primary_color} error={errors.brand_primary_color} onChange={(e) => setForm({ ...form, brand_primary_color: e.target.value.trim() })} />
        <Input label="Portal highlight colour" placeholder="#ea580c" hint={colourHint(form.brand_accent_color, 'accent')} value={form.brand_accent_color} error={errors.brand_accent_color} onChange={(e) => setForm({ ...form, brand_accent_color: e.target.value.trim() })} />
        <Input label="Account address" value={`${tenant.slug}`} disabled hint="Your sign-in address; contact support to change it." />
        <div className="sm:col-span-2">
          <Button type="submit" loading={save.isPending}>
            Save settings
          </Button>
        </div>
      </form>
    </Card>
  )
}

export function TenantSettingsPage() {
  const query = useQuery({ queryKey: ['tenant'], queryFn: () => api.get('/api/v1/tenant') })
  return (
    <>
      <PageHeader title="Settings" description="Account-wide defaults. Each location can set its own time zone." />
      {query.isPending ? <LoadingState /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <SettingsForm tenant={query.data} />}
      <BrandingCard />
    </>
  )
}
