import { useState } from 'react'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input } from '../../components/Field'

/** A secret the API returns exactly once (an API key, a webhook signing secret). It lives only in this
 * component's props: never in storage, never in a URL. */
export function SecretDialog({ title, secret, hint, onClose }: { title: string; secret: string; hint: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(secret)
    setCopied(true)
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      description="Copy it now. It is shown only once; if it is lost, rotate it to get a new one."
      footer={<Button onClick={onClose}>I have copied it</Button>}
    >
      <div className="flex items-end gap-2">
        <Input label="Secret" value={secret} readOnly className="flex-1 font-mono" onFocus={(e) => e.currentTarget.select()} hint={hint} />
        <Button variant="secondary" onClick={() => void copy()}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
    </Dialog>
  )
}
