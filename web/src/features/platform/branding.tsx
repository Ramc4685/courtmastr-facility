import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { FileUpload } from '../../components/FileUpload'
import { BrandMark } from '../../components/Icon'
import { Card } from '../../components/PageHeader'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { useAllLocations } from './queries'

export const useBranding = () =>
  useQuery({ queryKey: ['branding'], queryFn: () => api.get('/api/v1/public/branding'), staleTime: 5 * 60_000, retry: false })

/** The tenant's (or a location's) logo, else the product mark. Decorative: the account name always sits beside it. */
export function TenantLogo({ locationId, className = 'h-8 w-8' }: { locationId?: string | null; className?: string }) {
  const { data } = useBranding()
  const url = data?.locations.find((l) => l.location_id === locationId)?.logo_url ?? data?.tenant_logo_url
  return url ? <img src={url} alt="" className={`${className} rounded object-contain`} /> : <BrandMark className={className} />
}

const LOGO = { accept: ['image/png', 'image/jpeg'], maxBytes: 512 * 1024, hint: 'PNG or JPEG, up to 512 KB. Square images look best.' }

function LogoRow({ name, url, locationId }: { name: string; url: string | null | undefined; locationId?: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const saved = (data: Schemas['BrandingOut'], message: string) => {
    qc.setQueryData(['branding'], data)
    toast('success', message)
  }
  const remove = useMutation({
    mutationFn: () =>
      locationId ? api.delete('/api/v1/locations/{location_id}/logo', { path: { location_id: locationId } }) : api.delete('/api/v1/branding/logo'),
    onSuccess: (data) => saved(data, `Logo removed from ${name}.`),
  })
  return (
    <li className="flex flex-wrap items-start gap-4 border-t border-border pt-4 first:border-t-0 first:pt-0">
      <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded border border-border bg-surface-2">
        {url ? <img src={url} alt={`Current logo for ${name}`} className="h-14 w-14 object-contain" /> : <span className="text-xs text-muted">None</span>}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        {locationId ? (
          <FileUpload<Schemas['BrandingOut']>
            label={`Logo for ${name}`} purpose="location_logo" route="/api/v1/locations/{location_id}/logo" path={{ location_id: locationId }}
            {...LOGO} onUploaded={(data) => saved(data, `Logo saved for ${name}.`)}
          />
        ) : (
          <FileUpload<Schemas['BrandingOut']>
            label="Account logo" purpose="tenant_logo" route="/api/v1/branding/logo" {...LOGO} onUploaded={(data) => saved(data, 'Account logo saved.')}
          />
        )}
        {url && (
          <Button variant="secondary" size="sm" loading={remove.isPending} onClick={() => remove.mutate()}>
            Remove logo{locationId ? ` from ${name}` : ''}
          </Button>
        )}
      </div>
    </li>
  )
}

/** Logos shown in the staff sidebar and the member portal header; a location's logo replaces the account's there. */
export function BrandingCard() {
  const { can } = useAuth()
  const branding = useBranding()
  const locations = useAllLocations()
  const byLocation = new Map(branding.data?.locations.map((l) => [l.location_id, l.logo_url]))
  return (
    <Card title="Logos" className="mt-6 max-w-2xl">
      <p className="mb-4 text-sm text-muted">Logos are public images: anyone with the link can see them, so never upload anything private.</p>
      <ul className="space-y-4">
        <LogoRow name="the account" url={branding.data?.tenant_logo_url} />
        {can('platform.location.update') &&
          locations.data?.data.map((l) => <LogoRow key={l.id} name={l.name} url={byLocation.get(l.id)} locationId={l.id} />)}
      </ul>
    </Card>
  )
}
