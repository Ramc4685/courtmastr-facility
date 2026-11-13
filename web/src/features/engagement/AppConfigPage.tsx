import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { FormError } from '../billing/shared'
import { useBranding } from '../platform/branding'

type Config = Schemas['AppConfigOut']
type Tile = Schemas['AppTile']
type Form = Schemas['AppConfigReplace']

// The member app's built-in home (mobile/src/lib/tiles.tsx): shown when no layout is saved.
export const TILE_LABELS: Record<string, string> = {
  book: 'Book a class',
  card: 'My card',
  memberships: 'Memberships',
  invoices: 'Invoices',
  notifications: 'Notifications',
  facility: 'Facility info',
  news: 'News',
  contacts: 'Contacts',
  favorites: 'Favourites',
  feedback: 'Feedback',
  try_us: 'Try us',
}
// try_us is for visitors, so the built-in home (mobile/src/lib/tiles.tsx) leaves it out.
const BUILT_IN: Tile[] = Object.keys(TILE_LABELS).filter((type) => type !== 'try_us').map((type) => ({ type, caption: null, style: 'small' }))
const BUNDLED = { primary: '#1F6FEB', accent: '#0E9384' }
const label = (type: string) => TILE_LABELS[type] ?? type

// Tenant brand colours are data, not our tokens: the preview applies the app's own readability rule
// (mobile/src/lib/theme.ts) so staff see what members will see.
function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16)
  const ch = (c: number) => (c / 255 <= 0.03928 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4)
  return 0.2126 * ch((n >> 16) & 255) + 0.7152 * ch((n >> 8) & 255) + 0.0722 * ch(n & 255)
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}
const isHex = (v: string | null | undefined): v is string => Boolean(v && /^#[0-9a-f]{6}$/i.test(v))
const SURFACE = '#FFFFFF'
export function readable(color: string): string {
  let rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16))
  const hex = () => `#${rgb.map((c) => c.toString(16).padStart(2, '0')).join('')}`
  for (let i = 0; i < 20 && contrast(hex(), SURFACE) < 4.5; i++) rgb = rgb.map((c) => Math.round(c - c * 0.12))
  return hex().toUpperCase()
}
const onColor = (bg: string) => (contrast(bg, '#FFFFFF') >= contrast(bg, '#111827') ? '#FFFFFF' : '#111827')

type Brand = { primary_color?: string | null; accent_color?: string | null }

export function AppPreview({ form, facility, brand }: { form: Form; facility: string; brand?: Brand }) {
  const on = form.is_enabled ?? false
  const primary = readable(on && isHex(brand?.primary_color) ? brand.primary_color : BUNDLED.primary)
  const accent = readable(on && isHex(brand?.accent_color) ? brand.accent_color : BUNDLED.accent)
  const layout = form.home_screen
  const tiles = layout ? (layout.tiles ?? []) : BUILT_IN
  const columns = layout?.design?.columns ?? 2
  const radius = layout?.design?.corners === 'square' ? '4px' : '16px'
  return (
    <figure aria-labelledby="app-preview-caption" className="mx-auto w-full max-w-[300px]">
      <div className="overflow-hidden rounded-[28px] border-4 border-border bg-bg shadow-sm">
        <div className="px-4 py-3 text-sm font-semibold" style={{ backgroundColor: primary, color: onColor(primary) }}>
          {form.app_name?.trim() || facility}
        </div>
        <ul className="grid gap-2 p-3" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }} aria-label="Home tiles">
          {tiles.map((tile, i) => (
            <li
              key={`${tile.type}-${i}`}
              className="flex min-h-[64px] flex-col justify-end border border-border bg-surface p-3"
              style={{ borderRadius: radius, gridColumn: tile.style === 'large' && columns === 2 ? 'span 2' : undefined }}
            >
              <span aria-hidden className="mb-2 block h-1 w-6 rounded" style={{ backgroundColor: accent }} />
              <span className="text-sm font-semibold text-fg">{tile.caption?.trim() || label(tile.type)}</span>
            </li>
          ))}
          {tiles.length === 0 && <li className="text-sm text-muted">No tiles: members see only their next booking.</li>}
        </ul>
      </div>
      <figcaption id="app-preview-caption" className="mt-2 text-center text-xs text-muted">
        Live preview of the app home{form.is_enabled ? '' : ' (not live yet: the app keeps its built-in look until you switch these settings on)'}
      </figcaption>
    </figure>
  )
}

function toForm(c: Config): Form {
  return {
    mode: c.mode as Form['mode'], is_enabled: c.is_enabled, app_name: c.app_name ?? '', is_listed_in_directory: c.is_listed_in_directory,
    directory_name: c.directory_name ?? '', card_number_mode: c.card_number_mode as Form['card_number_mode'],
    features: c.features,
    home_screen: c.home_screen ?? null, schedule: c.schedule,
  }
}

function TileEditor({ tiles, types, onChange }: { tiles: Tile[]; types: string[]; onChange: (t: Tile[]) => void }) {
  const move = (i: number, by: number) => {
    const next = [...tiles]
    next.splice(i + by, 0, ...next.splice(i, 1))
    onChange(next)
  }
  const patch = (i: number, p: Partial<Tile>) => onChange(tiles.map((t, j) => (j === i ? { ...t, ...p } : t)))
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-semibold">Tiles, in order</legend>
      <ol className="space-y-3">
        {tiles.map((tile, i) => (
          <li key={i} className="grid grid-cols-1 gap-2 rounded border border-border p-3 sm:grid-cols-[1fr_1fr_8rem_auto] sm:items-end">
            <Select label={`Tile ${i + 1} type`} value={tile.type} options={types.map((t) => ({ value: t, label: label(t) }))} onChange={(e) => patch(i, { type: e.target.value })} />
            <Input label={`Tile ${i + 1} caption`} maxLength={40} placeholder={label(tile.type)} value={tile.caption ?? ''} onChange={(e) => patch(i, { caption: e.target.value || null })} />
            <Select label={`Tile ${i + 1} size`} value={tile.style ?? 'small'} options={[{ value: 'small', label: 'Small' }, { value: 'large', label: 'Large' }]} onChange={(e) => patch(i, { style: e.target.value as Tile['style'] })} />
            <div className="flex gap-1">
              <Button type="button" size="sm" variant="secondary" aria-label={`Move tile ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>↑</Button>
              <Button type="button" size="sm" variant="secondary" aria-label={`Move tile ${i + 1} down`} disabled={i === tiles.length - 1} onClick={() => move(i, 1)}>↓</Button>
              <Button type="button" size="sm" variant="danger" aria-label={`Remove tile ${i + 1}`} onClick={() => onChange(tiles.filter((_, j) => j !== i))}>Remove</Button>
            </div>
          </li>
        ))}
      </ol>
      <Button type="button" variant="secondary" disabled={tiles.length >= 12} onClick={() => onChange([...tiles, { type: types[0] ?? 'book', caption: null, style: 'small' }])}>Add a tile</Button>
    </fieldset>
  )
}

function ConfigForm({ config, facility }: { config: Config; facility: string }) {
  // shortcut: brand colours arrive with phase 11 chip A's /public/branding fields; untyped until that schema lands.
  const brand = useBranding().data as Brand | undefined
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState<Form>(() => toForm(config))
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }))
  const layout = form.home_screen
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/app-config', { body: { ...form, app_name: form.app_name || null, directory_name: form.directory_name || null } }),
    onSuccess: (saved) => {
      qc.setQueryData(['engagement', 'app-config'], saved)
      toast('success', 'App settings saved.')
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  const feature = (key: keyof NonNullable<Form['features']>, text: string) => (
    <Checkbox label={text} checked={form.features?.[key] ?? true} onChange={(e) => set({ features: { ...form.features, [key]: e.target.checked } })} />
  )
  return (
    <form onSubmit={submit} className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        <FormError error={save.error} />
        <Card title="App">
          <div className="space-y-4">
            <Checkbox label="Use these settings in the member app" checked={form.is_enabled ?? false} onChange={(e) => set({ is_enabled: e.target.checked })} />
            <Input label="App name" hint={`Shown at the top of the app. Empty uses ${facility}.`} maxLength={60} value={form.app_name ?? ''} error={errors.app_name} onChange={(e) => set({ app_name: e.target.value })} />
            <p className="text-sm text-muted">Colours and logo come from your account branding, the same as the online portal.</p>
          </div>
        </Card>
        <Card title="Facility search">
          <div className="space-y-4">
            <Checkbox label="List this facility in the shared app's search" hint="Only locations whose portal is on and public make it findable." checked={form.is_listed_in_directory ?? false} onChange={(e) => set({ is_listed_in_directory: e.target.checked })} />
            <Input label="Name in search" hint="Empty uses the facility name." maxLength={80} value={form.directory_name ?? ''} error={errors.directory_name} onChange={(e) => set({ directory_name: e.target.value })} />
          </div>
        </Card>
        <Card title="Home screen">
          <div className="space-y-4">
            <Checkbox label="Use a custom home layout" hint="Off shows the app's built-in tiles." checked={layout !== null} onChange={(e) => set({ home_screen: e.target.checked ? { tiles: BUILT_IN, design: { columns: 2, corners: 'rounded' } } : null })} />
            {layout && (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Select label="Columns" value={String(layout.design?.columns ?? 2)} options={[{ value: '2', label: 'Two' }, { value: '1', label: 'One' }]} onChange={(e) => set({ home_screen: { ...layout, design: { ...layout.design, columns: Number(e.target.value) as 1 | 2 } } })} />
                  <Select label="Corners" value={layout.design?.corners ?? 'rounded'} options={[{ value: 'rounded', label: 'Rounded' }, { value: 'square', label: 'Square' }]} onChange={(e) => set({ home_screen: { ...layout, design: { ...layout.design, corners: e.target.value as 'rounded' | 'square' } } })} />
                </div>
                <TileEditor tiles={layout.tiles ?? []} types={config.tile_types} onChange={(tiles) => set({ home_screen: { ...layout, tiles } })} />
              </>
            )}
          </div>
        </Card>
        <Card title="Schedule">
          <div className="space-y-4">
            <Checkbox label="Show spots left" checked={form.schedule?.shows_spots_left ?? true} onChange={(e) => set({ schedule: { ...form.schedule, shows_spots_left: e.target.checked } })} />
            <Checkbox label="Show full sessions" hint="Each location's booking policy can hide them too." checked={form.schedule?.shows_full_sessions ?? true} onChange={(e) => set({ schedule: { ...form.schedule, shows_full_sessions: e.target.checked } })} />
            <Input label="Days ahead shown" hint="1 to 365. Empty follows each booking policy." type="number" min={1} max={365} value={form.schedule?.days_ahead ?? ''} error={errors['schedule/days_ahead'] ?? errors.days_ahead} onChange={(e) => set({ schedule: { ...form.schedule, days_ahead: e.target.value ? Number(e.target.value) : null } })} />
          </div>
        </Card>
        <Card title="Features">
          <div className="space-y-3">
            {feature('booking', 'Booking')}
            {feature('purchases', 'Buying packages and memberships')}
            {feature('membership_card', 'Check-in card')}
            {feature('wallet_pass', 'Wallet pass')}
          </div>
        </Card>
        <Button type="submit" loading={save.isPending}>Save app settings</Button>
      </div>
      <div className="lg:sticky lg:top-4 lg:self-start">
        <AppPreview form={form} facility={facility} brand={brand} />
      </div>
    </form>
  )
}

export function AppConfigPage() {
  const me = useMe()
  const config = useQuery({ queryKey: ['engagement', 'app-config'], queryFn: () => api.get('/api/v1/app-config') })
  return (
    <>
      <PageHeader title="Member app" description="Home screen, schedule display and facility search for the member app, for every location." />
      {config.isPending ? <LoadingState /> : config.isError ? <ErrorState error={config.error} onRetry={() => config.refetch()} /> : (
        <ConfigForm config={config.data} facility={me.tenant.name} />
      )}
    </>
  )
}
