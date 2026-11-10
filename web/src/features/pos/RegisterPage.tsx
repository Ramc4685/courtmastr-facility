import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { formatMoney, parseMoney, toMoneyInput } from '../billing/money'
import { PaymentMethodField } from '../billing/PaymentMethodField'
import { Money, StatusBadge, useCurrency, useLocationRef } from '../billing/shared'
import { TENDER_STATUS, useRegisters, type Sale } from './shared'

type Session = Schemas['RegisterSession']
const sessionKey = (id: string) => ['pos', 'register-session', id]

/** /pos: choose the register this screen is. The choice lives in the URL, so a bookmark opens the register. */
export function RegisterPickerPage() {
  const registers = useRegisters()
  const navigate = useNavigate()
  if (registers.isPending) return <LoadingState />
  if (registers.isError) return <ErrorState error={registers.error} />
  const active = registers.data.data.filter((r) => r.is_active)
  if (active.length === 1 && active[0]) {
    return <RegisterRedirect to={`/pos/register/${active[0].id}`} />
  }
  return (
    <>
      <PageHeader title="Register" description="Choose the register at this desk." />
      {active.length === 0 ? (
        <EmptyState title="No registers yet" action={<Link className="font-medium text-primary underline" to="/pos/setup">Add one in set-up</Link>} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {active.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => navigate(`/pos/register/${r.id}`)} className="w-full rounded-lg border border-border bg-surface p-4 text-left shadow-card hover:border-primary">
                <span className="block font-semibold">{r.name}</span>
                <RegisterLocation id={r.location_id} />
                <span className="mt-2 block text-sm">{r.open_drawer_session_id ? 'Drawer open' : 'Drawer closed'}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function RegisterRedirect({ to }: { to: string }) {
  const navigate = useNavigate()
  useEffect(() => navigate(to, { replace: true }), [navigate, to])
  return <LoadingState />
}

function RegisterLocation({ id }: { id: string }) {
  return <span className="block text-sm text-muted">{useLocationRef(id)?.name ?? ''}</span>
}

export function RegisterPage() {
  const { registerId = '' } = useParams()
  const session = useQuery({ queryKey: sessionKey(registerId), queryFn: () => api.get('/api/v1/registers/{register_id}/session', { path: { register_id: registerId } }) })
  if (session.isPending) return <LoadingState label="Loading the register" />
  if (session.isError) {
    const blocked = session.error instanceof ApiError && session.error.code === 'network-not-allowed'
    return blocked ? (
      <EmptyState title="This register cannot be used from here">The location only allows its register on the club&apos;s own network. Ask a manager to check the allowed networks in POS set-up.</EmptyState>
    ) : (
      <ErrorState error={session.error} onRetry={() => session.refetch()} />
    )
  }
  return <Register session={session.data} />
}

function OpenDrawer({ session }: { session: Session }) {
  const qc = useQueryClient()
  const [float, setFloat] = useState('0.00')
  const open = useMutation({
    mutationFn: () => api.post('/api/v1/registers/{register_id}/drawer-sessions', { path: { register_id: session.register.id }, body: { opening_float_minor: parseMoney(float) ?? 0 } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: sessionKey(session.register.id) }),
  })
  return (
    <Card title="Open the drawer">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          open.mutate()
        }}
      >
        <Input label="Opening float" inputMode="decimal" value={float} onChange={(e) => setFloat(e.target.value)} error={open.error?.message} />
        <Button type="submit" loading={open.isPending}>
          Open drawer
        </Button>
      </form>
    </Card>
  )
}

function Register({ session }: { session: Session }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const registerId = session.register.id
  const [saleId, setSaleId] = useState<string | null>(session.draft_sale_id ?? null)
  const [done, setDone] = useState<Sale | null>(null)
  const sale = useQuery({
    queryKey: ['pos', 'sale', saleId],
    queryFn: () => api.get('/api/v1/pos-sales/{pos_sale_id}', { path: { pos_sale_id: saleId ?? '' } }),
    enabled: Boolean(saleId),
    initialData: session.draft_sale && session.draft_sale.id === saleId ? session.draft_sale : undefined,
  })
  const put = (s: Sale) => qc.setQueryData(['pos', 'sale', s.id], s)
  const refresh = () => qc.invalidateQueries({ queryKey: ['pos', 'sale', saleId] })
  const onError = (e: Error) => {
    toast('error', e.message)
    void refresh()
  }

  const start = useMutation({
    mutationFn: () => api.post('/api/v1/pos-sales', { body: { register_id: registerId } }),
    onSuccess: (s) => {
      put(s)
      setSaleId(s.id)
      setDone(null)
    },
    onError,
  })
  const ensureSale = async () => saleId ?? (await start.mutateAsync()).id

  if (!session.drawer_session && session.settings.is_drawer_session_required) {
    return (
      <>
        <PageHeader title={session.register.name} description="Open the cash drawer before the first sale." />
        <OpenDrawer session={session} />
      </>
    )
  }
  const current = saleId ? sale.data : undefined
  return (
    <>
      <PageHeader
        title={session.register.name}
        description={session.drawer_session ? `Drawer open since ${new Date(session.drawer_session.opened_at).toLocaleTimeString()}` : 'No drawer open: cash still counts against the register.'}
        actions={
          <div className="flex gap-2">
            {!session.drawer_session && can('pos.drawer.operate') && <OpenDrawerButton registerId={registerId} />}
            <Link className="self-center text-sm font-medium text-primary underline" to="/pos/drawers">
              Drawer
            </Link>
          </div>
        }
      />
      {done && <SaleDone sale={done} onNext={() => setDone(null)} />}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-6">
          <AddItems session={session} ensureSale={ensureSale} onSale={put} onError={onError} />
          {current ? <Cart session={session} sale={current} onSale={put} onError={onError} onAbandoned={() => setSaleId(null)} /> : <Card title="Cart"><p className="text-sm text-muted">Scan an item or pick one to start a sale.</p></Card>}
        </div>
        {current && (
          <Checkout
            session={session}
            sale={current}
            onSale={put}
            onError={onError}
            onDone={(s) => {
              setDone(s)
              setSaleId(null)
              void qc.invalidateQueries({ queryKey: sessionKey(registerId) })
            }}
          />
        )}
      </div>
    </>
  )
}

function OpenDrawerButton({ registerId }: { registerId: string }) {
  const qc = useQueryClient()
  const open = useMutation({
    mutationFn: () => api.post('/api/v1/registers/{register_id}/drawer-sessions', { path: { register_id: registerId }, body: { opening_float_minor: 0 } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: sessionKey(registerId) }),
  })
  return (
    <Button variant="secondary" loading={open.isPending} onClick={() => open.mutate()}>
      Open drawer
    </Button>
  )
}

type SaleProps = { session: Session; sale: Sale; onSale: (s: Sale) => void; onError: (e: Error) => void }
type CartProps = SaleProps & { onAbandoned: () => void }

/** The barcode field is a keyboard wedge target: scanners type the code and press Enter. Focus returns to it
 * after every scan so the next item can go straight in. */
function AddItems({ session, ensureSale, onSale, onError }: { session: Session; ensureSale: () => Promise<string>; onSale: (s: Sale) => void; onError: (e: Error) => void }) {
  const [code, setCode] = useState('')
  const [search, setSearch] = useState('')
  const scanRef = useRef<HTMLFormElement>(null)
  const location = session.register.location_id
  const add = useMutation({
    mutationFn: async (body: Schemas['PosSaleLineCreate']) => {
      const id = await ensureSale()
      return api.post('/api/v1/pos-sales/{pos_sale_id}/lines', { path: { pos_sale_id: id }, body })
    },
    onSuccess: (s) => {
      onSale(s)
      setCode('')
      scanRef.current?.querySelector('input')?.focus()
    },
    onError,
  })
  const favorites = useQuery({
    queryKey: ['pos', 'favorites', session.register.id, session.register.favorite_product_ids],
    queryFn: () => api.get('/api/v1/products', { query: { limit: 200, location_id: location, is_active: true } }),
    enabled: session.register.is_favorites_enabled && session.register.favorite_product_ids.length > 0,
  })
  const found = useQuery({
    queryKey: ['pos', 'product-search', location, search],
    queryFn: () => api.get('/api/v1/products', { query: { q: search, limit: 10, location_id: location, is_active: true } }),
    enabled: search.trim().length >= 2,
  })
  const equipment = useQuery({
    queryKey: ['pos', 'equipment-items', 'rentable', location],
    queryFn: () => api.get('/api/v1/equipment-items', { query: { location_id: location, is_active: true, limit: 200 } }),
  })
  const [rental, setRental] = useState('')
  const favs = (favorites.data?.data ?? []).filter((p) => session.register.favorite_product_ids.includes(p.id))
  const scan = (e: FormEvent) => {
    e.preventDefault()
    if (code.trim()) add.mutate({ sku: code.trim(), quantity: 1 })
  }
  return (
    <Card title="Add items">
      <form ref={scanRef} onSubmit={scan} className="flex items-end gap-2">
        <Input label="Scan or type a barcode" className="flex-1" autoFocus autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)} hint="A barcode scanner types here and presses Enter. The product code works too." />
        <Button type="submit" loading={add.isPending} className="mb-6">
          Add
        </Button>
      </form>
      {favs.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold">Favourites</h3>
          <div className="flex flex-wrap gap-2">
            {favs.map((p) => (
              <Button key={p.id} variant="secondary" size="sm" onClick={() => add.mutate({ product_id: p.id, quantity: 1 })}>
                {p.name}
              </Button>
            ))}
          </div>
        </div>
      )}
      <div className="mt-4 space-y-2">
        <Input label="Find a product" type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
        {found.data && (
          <ul aria-label="Matching products" className="divide-y divide-border rounded border border-border">
            {found.data.data.length === 0 && <li className="p-2 text-sm text-muted">No products match.</li>}
            {found.data.data.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 p-2 text-sm">
                <span>
                  {p.name} <span className="text-muted">{p.product_code}</span>
                  {p.is_stock_tracked && p.on_hand_count != null && <span className="text-muted"> · {p.on_hand_count} on hand</span>}
                </span>
                <span className="flex items-center gap-2">
                  <Money minor={p.unit_price_minor} />
                  <Button size="sm" variant="ghost" aria-label={`Add ${p.name}`} onClick={() => add.mutate({ product_id: p.id, quantity: 1 })}>
                    Add
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {(equipment.data?.data.length ?? 0) > 0 && (
        <form
          className="mt-4 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (rental) add.mutate({ equipment_item_id: rental, quantity: 1 })
          }}
        >
          <Select
            label="Rent equipment"
            className="flex-1"
            value={rental}
            onChange={(e) => setRental(e.target.value)}
            placeholder="Choose an item"
            options={(equipment.data?.data ?? []).map((i) => ({ value: i.id, label: `${i.name} (${i.asset_code}) · ${i.available_count} free` }))}
            hint="Rentals need a client on the sale."
          />
          <Button type="submit" variant="secondary" className="mb-6" disabled={!rental}>
            Rent
          </Button>
        </form>
      )}
    </Card>
  )
}

function LineRow({ session, sale, line, onSale, onError }: SaleProps & { line: Sale['lines'][number] }) {
  const qc = useQueryClient()
  const [qty, setQty] = useState(String(line.quantity))
  const [price, setPrice] = useState(toMoneyInput(line.unit_price_minor))
  useEffect(() => setQty(String(line.quantity)), [line.quantity])
  useEffect(() => setPrice(toMoneyInput(line.unit_price_minor)), [line.unit_price_minor])
  const update = useMutation({
    mutationFn: (body: Schemas['PosSaleLineUpdate']) => api.patch('/api/v1/pos-sales/{pos_sale_id}/lines/{pos_sale_line_id}', { path: { pos_sale_id: sale.id, pos_sale_line_id: line.id }, body }),
    onSuccess: onSale,
    onError,
  })
  const remove = useMutation({
    mutationFn: () => api.delete('/api/v1/pos-sales/{pos_sale_id}/lines/{pos_sale_line_id}', { path: { pos_sale_id: sale.id, pos_sale_line_id: line.id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pos', 'sale', sale.id] }),
    onError,
  })
  const locked = sale.tendered_minor > 0
  return (
    <tr>
      <td className="px-3 py-2">
        {line.description}
        {line.line_kind === 'equipment' && <Badge tone="info">Rental</Badge>}
        {line.price_overridden_by_staff_user_id && (
          <span className="block text-xs text-muted">
            List <Money minor={line.list_unit_price_minor} />
          </span>
        )}
      </td>
      <td className="px-3 py-2">
        <Input
          label={<span className="sr-only">Quantity of {line.description}</span>}
          className="w-20"
          inputMode="numeric"
          value={qty}
          disabled={locked}
          onChange={(e) => setQty(e.target.value)}
          onBlur={() => Number(qty) !== line.quantity && Number(qty) > 0 && update.mutate({ quantity: Number(qty) })}
        />
      </td>
      <td className="px-3 py-2">
        {session.can_override_price && !locked ? (
          <Input
            label={<span className="sr-only">Price of {line.description}</span>}
            className="w-24"
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            onBlur={() => {
              const minor = parseMoney(price)
              if (minor !== null && minor !== line.unit_price_minor) update.mutate({ unit_price_minor: minor })
            }}
          />
        ) : (
          <Money minor={line.unit_price_minor} />
        )}
      </td>
      <td className="px-3 py-2 text-right">
        <Money minor={line.total_minor} />
        {line.discount_minor > 0 && (
          <span className="block text-xs text-muted">
            −<Money minor={line.discount_minor} />
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        <Button size="sm" variant="ghost" aria-label={`Remove ${line.description}`} disabled={locked} loading={remove.isPending} onClick={() => remove.mutate()}>
          Remove
        </Button>
      </td>
    </tr>
  )
}

function Cart({ onAbandoned, ...props }: CartProps) {
  const { sale, session, onSale, onError } = props
  const qc = useQueryClient()
  const { can } = useAuth()
  const [client, setClient] = useState<ClientSummary | null>(null)
  const setClientOnSale = useMutation({
    mutationFn: (c: ClientSummary | null) => api.patch('/api/v1/pos-sales/{pos_sale_id}', { path: { pos_sale_id: sale.id }, body: { version: sale.version, client_id: c?.id ?? null } }),
    onSuccess: onSale,
    onError,
  })
  const abandon = useMutation({
    mutationFn: () => api.post('/api/v1/pos-sales/{pos_sale_id}/abandon', { path: { pos_sale_id: sale.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: sessionKey(session.register.id) })
      onAbandoned()
    },
    onError,
  })
  return (
    <Card title="Cart">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        {sale.client_id ? (
          <p className="text-sm">
            Client: <span className="font-medium">{sale.client_name}</span>{' '}
            <Button size="sm" variant="ghost" disabled={sale.tendered_minor > 0} onClick={() => setClientOnSale.mutate(null)}>
              Walk-in instead
            </Button>
          </p>
        ) : can('clients.client.read') ? (
          <div className="min-w-64 flex-1">
            <ClientPicker
              label="Client (optional)"
              value={client}
              hint="Leave empty for a walk-in."
              disabled={sale.tendered_minor > 0}
              onChange={(c) => {
                setClient(c)
                if (c) setClientOnSale.mutate(c)
              }}
            />
          </div>
        ) : (
          <p className="text-sm text-muted">Walk-in sale</p>
        )}
      </div>
      {sale.lines.length === 0 ? (
        <p className="text-sm text-muted">The cart is empty.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Items in the cart</caption>
            <thead className="text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-3 py-2">Item</th>
                <th scope="col" className="px-3 py-2">Qty</th>
                <th scope="col" className="px-3 py-2">Price</th>
                <th scope="col" className="px-3 py-2 text-right">Total</th>
                <th scope="col" className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sale.lines.map((l) => (
                <LineRow key={l.id} {...props} line={l} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Discounts {...props} />
      <div className="mt-4 flex justify-end">
        <Button variant="ghost" loading={abandon.isPending} disabled={sale.tendered_minor > 0} onClick={() => abandon.mutate()}>
          Abandon sale
        </Button>
      </div>
    </Card>
  )
}

function Discounts({ session, sale, onSale, onError }: SaleProps) {
  const qc = useQueryClient()
  const currency = useCurrency()
  const [preset, setPreset] = useState('')
  const [amount, setAmount] = useState('')
  const [coupon, setCoupon] = useState('')
  const add = useMutation({
    mutationFn: (body: Schemas['PosSaleDiscountCreate']) => api.post('/api/v1/pos-sales/{pos_sale_id}/discounts', { path: { pos_sale_id: sale.id }, body }),
    onSuccess: (s) => {
      onSale(s)
      setPreset('')
      setAmount('')
      setCoupon('')
    },
    onError,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/pos-sales/{pos_sale_id}/discounts/{pos_sale_discount_id}', { path: { pos_sale_id: sale.id, pos_sale_discount_id: id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pos', 'sale', sale.id] }),
    onError,
  })
  if (sale.lines.length === 0) return null
  return (
    <section aria-labelledby="discounts-heading" className="mt-6 space-y-3">
      <h3 id="discounts-heading" className="text-sm font-semibold">
        Discounts
      </h3>
      {sale.discounts.length > 0 && (
        <ul className="divide-y divide-border rounded border border-border text-sm">
          {sale.discounts.map((d) => (
            <li key={d.id} className="flex items-center justify-between p-2">
              <span>
                {d.label} {d.scope === 'lines' && <span className="text-muted">(selected items)</span>}
              </span>
              <span className="flex items-center gap-2">
                −{formatMoney(d.applied_minor, currency)}
                {d.source !== 'product_default' && (
                  <Button size="sm" variant="ghost" aria-label={`Remove discount ${d.label}`} disabled={sale.tendered_minor > 0} onClick={() => remove.mutate(d.id)}>
                    Remove
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        {session.discount_presets.length > 0 && (
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (preset) add.mutate({ source: 'preset', scope: 'sale', discount_preset_id: preset })
            }}
          >
            <Select label="Preset" className="flex-1" value={preset} placeholder="Choose" onChange={(e) => setPreset(e.target.value)} options={session.discount_presets.map((p) => ({ value: p.id, label: p.name }))} />
            <Button type="submit" variant="secondary" size="sm" disabled={!preset}>
              Apply
            </Button>
          </form>
        )}
        {session.can_apply_custom_discount && (
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              const minor = parseMoney(amount)
              if (minor) add.mutate({ source: 'custom', scope: 'sale', discount_minor: minor })
            }}
          >
            <Input label="Amount off" className="flex-1" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <Button type="submit" variant="secondary" size="sm" disabled={!amount}>
              Apply
            </Button>
          </form>
        )}
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (coupon.trim()) add.mutate({ source: 'coupon', scope: 'sale', coupon_code: coupon.trim() })
          }}
        >
          <Input label="Coupon code" className="flex-1" autoComplete="off" value={coupon} onChange={(e) => setCoupon(e.target.value)} />
          <Button type="submit" variant="secondary" size="sm" disabled={!coupon.trim()}>
            Apply
          </Button>
        </form>
      </div>
    </section>
  )
}

function Checkout({ session, sale, onSale, onError, onDone }: SaleProps & { onDone: (s: Sale) => void }) {
  const qc = useQueryClient()
  const currency = useCurrency()
  const tenders = session.tender_types.filter((t) => t.is_enabled)
  const [tenderType, setTenderType] = useState(tenders.find((t) => t.kind === 'cash')?.id ?? tenders[0]?.id ?? '')
  const [amount, setAmount] = useState('')
  const [received, setReceived] = useState('')
  const [token, setToken] = useState('')
  const kind = tenders.find((t) => t.id === tenderType)?.kind
  const due = sale.remaining_minor
  const value = amount === '' ? due : (parseMoney(amount) ?? 0)
  const change = kind === 'cash' && received ? (parseMoney(received) ?? 0) - value : 0
  const pay = useMutation({
    mutationFn: (body: Schemas['PosSaleTenderCreate']) => api.post('/api/v1/pos-sales/{pos_sale_id}/tenders', { path: { pos_sale_id: sale.id }, body }),
    onSuccess: (s) => {
      onSale(s)
      setAmount('')
      setReceived('')
    },
    onError,
  })
  const removeTender = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/pos-sales/{pos_sale_id}/tenders/{pos_sale_tender_id}', { path: { pos_sale_id: sale.id, pos_sale_tender_id: id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pos', 'sale', sale.id] }),
    onError,
  })
  const complete = useMutation({
    mutationFn: () => api.post('/api/v1/pos-sales/{pos_sale_id}/complete', { path: { pos_sale_id: sale.id } }),
    onSuccess: onDone,
    onError,
  })
  const ready = sale.lines.length > 0 && due === 0 && !sale.tenders.some((t) => t.status === 'pending')
  return (
    <div className="space-y-6">
      <Card title="Total">
        <dl className="space-y-1 text-sm">
          <div className="flex justify-between"><dt>Subtotal</dt><dd><Money minor={sale.subtotal_minor} /></dd></div>
          <div className="flex justify-between"><dt>Discounts</dt><dd>−<Money minor={sale.discount_minor} /></dd></div>
          <div className="flex justify-between"><dt>Tax</dt><dd><Money minor={sale.tax_minor} /></dd></div>
          <div className="flex justify-between border-t border-border pt-2 text-lg font-semibold"><dt>Total</dt><dd><Money minor={sale.total_minor} /></dd></div>
          <div className="flex justify-between"><dt>Paid</dt><dd><Money minor={sale.tendered_minor} /></dd></div>
          <div className="flex justify-between font-semibold"><dt>Still due</dt><dd><Money minor={due} /></dd></div>
        </dl>
        <p className="sr-only" role="status" aria-live="polite">
          Still due {formatMoney(due, currency)}
        </p>
      </Card>
      <Card title="Payment">
        {sale.tenders.length > 0 && (
          <ul aria-label="Tenders" className="mb-4 divide-y divide-border rounded border border-border text-sm">
            {sale.tenders.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-2 p-2">
                <span>
                  {t.tender === 'pay_later' ? 'Pay later (on account)' : t.tender === 'account_credit' ? 'Account credit' : (tenders.find((x) => x.id === t.tender_type_id)?.label ?? t.tender_kind ?? 'Payment')}{' '}
                  <StatusBadge map={TENDER_STATUS} value={t.status} />
                </span>
                <span className="flex items-center gap-2">
                  <Money minor={t.amount_minor} />
                  {(t.status === 'captured' || t.status === 'pending') && (
                    <Button size="sm" variant="ghost" aria-label={`Remove tender of ${formatMoney(t.amount_minor, currency)}`} onClick={() => removeTender.mutate(t.id)}>
                      Remove
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
        {due > 0 && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              pay.mutate({
                tender: 'payment',
                tender_type_id: tenderType,
                amount_minor: value,
                cash_received_minor: kind === 'cash' && received ? parseMoney(received) : null,
                provider_confirmation_token: kind === 'card' ? token || null : null,
              })
            }}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <Select label="Tender" value={tenderType} onChange={(e) => setTenderType(e.target.value)} options={tenders.map((t) => ({ value: t.id, label: t.label }))} />
              <Input label="Amount" inputMode="decimal" value={amount} placeholder={toMoneyInput(due)} onChange={(e) => setAmount(e.target.value)} hint="Empty: the amount still due." />
            </div>
            {kind === 'cash' && (
              <Input label="Cash handed over" inputMode="decimal" value={received} onChange={(e) => setReceived(e.target.value)} hint={change > 0 ? `Change due: ${formatMoney(change, currency)}` : 'Optional: works out the change.'} />
            )}
            {kind === 'card' && <PaymentMethodField kind="card" value={token} onChange={setToken} label="Card" />}
            <Button type="submit" loading={pay.isPending} disabled={value <= 0}>
              Take {formatMoney(value, currency)}
            </Button>
          </form>
        )}
        {due > 0 && sale.client_id && (
          <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
            <Button variant="secondary" size="sm" onClick={() => pay.mutate({ tender: 'pay_later', amount_minor: due })}>
              Put the rest on account
            </Button>
            <Button variant="secondary" size="sm" onClick={() => pay.mutate({ tender: 'account_credit', amount_minor: due })}>
              Use account credit
            </Button>
          </div>
        )}
        <Button className="mt-6 w-full" disabled={!ready} loading={complete.isPending} onClick={() => complete.mutate()}>
          Complete sale
        </Button>
      </Card>
    </div>
  )
}

function SaleDone({ sale, onNext }: { sale: Sale; onNext: () => void }) {
  const toast = useToast()
  const [email, setEmail] = useState('')
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/pos-sales/{pos_sale_id}/receipt-deliveries', { path: { pos_sale_id: sale.id }, body: { channel: 'email', to_email: email } }),
    onSuccess: () => toast('success', `Receipt sent to ${email}.`),
    onError: (e) => toast('error', e.message),
  })
  return (
    <div role="status" className="mb-6 flex flex-wrap items-end justify-between gap-4 rounded-lg border border-success/40 bg-success/10 p-4">
      <div>
        <p className="font-semibold">Sale #{sale.invoice_number} complete · <Money minor={sale.total_minor} /></p>
        <Link className="text-sm font-medium text-primary underline" to={`/pos/sales/${sale.id}/receipt`}>
          Print receipt
        </Link>
      </div>
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (email) send.mutate()
        }}
      >
        <Input label="Email the receipt" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Button type="submit" variant="secondary" loading={send.isPending} disabled={!email}>
          Send
        </Button>
      </form>
      <Button onClick={onNext}>Next sale</Button>
    </div>
  )
}
