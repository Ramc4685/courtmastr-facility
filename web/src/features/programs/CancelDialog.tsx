import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { programError } from './queries'

type Choice<T extends string> = { value: T; label: string }
function Radios<T extends string>({ legend, name, value, options, onChange }: { legend: string; name: string; value: T; options: Choice<T>[]; onChange: (v: T) => void }) {
  return (
    <fieldset className="space-y-1.5">
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      {options.map((o) => (
        <label key={o.value} className="flex items-center gap-2 text-sm">
          <input type="radio" name={name} className="accent-[rgb(var(--primary))]" checked={value === o.value} onChange={() => onChange(o.value)} />
          {o.label}
        </label>
      ))}
    </fieldset>
  )
}

/** Cancel one registration: why, what happens to the charge, whether the place goes to the waitlist, and (for
 * a session batch) whether the rest of the batch goes too. */
export function CancelDialog({ enrollmentId, who, showScope = false, onClose, onDone }: { enrollmentId: string; who: string; showScope?: boolean; onClose: () => void; onDone?: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [kind, setKind] = useState<'early' | 'late' | 'staff_removed'>('staff_removed')
  const [billing, setBilling] = useState<'none' | 'kept' | 'reversed'>('none')
  const [waitlist, setWaitlist] = useState(false)
  const [scope, setScope] = useState<'single' | 'batch'>('single')
  const cancel = useMutation({
    mutationFn: () =>
      api.post('/api/v1/enrollments/{enrollment_id}/cancel', {
        path: { enrollment_id: enrollmentId },
        body: { cancel_kind: kind, billing_disposition: billing, add_to_waitlist: waitlist, scope },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['program-group'] })
      void qc.invalidateQueries({ queryKey: ['program-groups'] })
      void qc.invalidateQueries({ queryKey: ['session'] })
      toast('success', `${who} cancelled.`)
      onDone?.()
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Cancel ${who}?`}
      description="The place is released. The registration stays in the history as cancelled."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Keep registration
          </Button>
          <Button variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}>
            Cancel registration
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {cancel.error && (
          <p role="alert" className="text-danger">
            {programError(cancel.error)}
          </p>
        )}
        <Select label="Reason" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} options={[{ value: 'staff_removed', label: 'Removed by staff' }, { value: 'early', label: 'Client cancelled in time' }, { value: 'late', label: 'Client cancelled late' }]} />
        <Radios legend="Charge" name="billing" value={billing} onChange={setBilling} options={[{ value: 'none', label: 'Nothing billed, or leave as is' }, { value: 'kept', label: 'Keep the charge' }, { value: 'reversed', label: 'Reverse the charge' }]} />
        {showScope && <Radios legend="Applies to" name="scope" value={scope} onChange={setScope} options={[{ value: 'single', label: 'This one only' }, { value: 'batch', label: 'Every session booked together' }]} />}
        <Checkbox label="Add the client to the waitlist" checked={waitlist} onChange={(e) => setWaitlist(e.target.checked)} />
      </div>
    </Dialog>
  )
}
