import { Input, Select } from '../../components/Field'
import { SignaturePad } from './SignaturePad'

export type SignerState = { name: string; method: 'typed_name' | 'drawn_signature'; typed: string; png: string | null; clientId: string }
export const emptySigner = (name = ''): SignerState => ({ name, method: 'typed_name', typed: name, png: null, clientId: '' })
export const ROLE_LABEL: Record<string, string> = { client: 'Client', guardian: 'Parent or guardian', co_signer: 'Co-signer' }

export const signerReady = (s: SignerState) => Boolean(s.name.trim()) && (s.method === 'typed_name' ? Boolean(s.typed.trim()) : Boolean(s.png))

/** One signer's name and signature: typed (always available) or drawn. */
export function SignerFields({
  role,
  value,
  onChange,
  guardians,
}: {
  role: string
  value: SignerState
  onChange: (next: SignerState) => void
  guardians?: { id: string; name: string }[]
}) {
  const label = ROLE_LABEL[role] ?? role
  return (
    <fieldset className="space-y-3 rounded border border-border p-4">
      <legend className="px-1 text-sm font-semibold">{label}</legend>
      {guardians && guardians.length > 0 && (
        <Select
          label="Guardian on file"
          value={value.clientId}
          onChange={(e) => {
            const picked = guardians.find((g) => g.id === e.target.value)
            onChange({ ...value, clientId: e.target.value, name: picked?.name ?? value.name, typed: picked?.name ?? value.typed })
          }}
          placeholder="Choose a guardian"
          options={guardians.map((g) => ({ value: g.id, label: g.name }))}
        />
      )}
      <Input label={`${label} full name`} value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} required />
      <Select
        label="Signature method"
        value={value.method}
        onChange={(e) => onChange({ ...value, method: e.target.value as SignerState['method'] })}
        options={[
          { value: 'typed_name', label: 'Type name as signature' },
          { value: 'drawn_signature', label: 'Draw signature' },
        ]}
      />
      {value.method === 'typed_name' ? (
        <Input label="Typed signature" hint="Typing your name here signs the document." value={value.typed} onChange={(e) => onChange({ ...value, typed: e.target.value })} />
      ) : (
        <SignaturePad label={`${label} signature`} onChange={(png) => onChange({ ...value, png })} />
      )}
    </fieldset>
  )
}

export function toSigner(role: string, s: SignerState, decision: 'accepted' | 'declined' = 'accepted') {
  return {
    decision,
    signer_role: role as 'client' | 'guardian' | 'co_signer',
    signer_name: s.name.trim(),
    signer_client_id: s.clientId || null,
    method: s.method,
    typed_signature: s.method === 'typed_name' ? s.typed.trim() : null,
    signature_png: s.method === 'drawn_signature' ? s.png : null,
  }
}
