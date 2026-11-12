import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, downloadFile, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input } from '../../components/Field'
import { EmptyState } from '../../components/States'
import { useToast } from '../../components/Toast'
import type { Game } from './queries'

export function Alert({ error }: { error: Error | null }) {
  if (!error || Object.keys(fieldErrors(error)).length) return null
  return <p role="alert" className="text-danger sm:col-span-2">{error.message}</p>
}

/** A plain table for lists the API returns whole (team entries, standings, a competition's games). */
export function List<T>({ caption, rows, columns, rowKey, empty }: { caption: string; rows: T[]; columns: { header: string; cell: (r: T) => ReactNode }[]; rowKey: (r: T) => string; empty: string }) {
  if (rows.length === 0) return <EmptyState title={empty} />
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>{columns.map((c) => <th key={c.header} scope="col" className="px-4 py-2.5 font-semibold">{c.header}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={rowKey(r)}>{columns.map((c) => <td key={c.header} className="px-4 py-2.5">{c.cell(r)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export const matchup = (g: Game) => `${g.home_name ?? g.home_label ?? 'TBD'} vs ${g.away_name ?? g.away_label ?? 'TBD'}`

const side = (score: string) => ({ score: Number(score), participation: 'full' as const, went_to_overtime: false, bonus_points: 0 })

export function ScoreDialog({ game, onClose }: { game: Game; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [home, setHome] = useState(game.home_score === null || game.home_score === undefined ? '' : String(game.home_score))
  const [away, setAway] = useState(game.away_score === null || game.away_score === undefined ? '' : String(game.away_score))
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/games/{game_id}/result', { path: { game_id: game.id }, body: { home: side(home), away: side(away) } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['competition', game.competition_id] })
      void qc.invalidateQueries({ queryKey: ['score-games'] })
      toast('success', 'Result saved; the standings are updated.')
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Score: ${game.home_name ?? game.home_label} vs ${game.away_name ?? game.away_label}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="score-form" loading={save.isPending}>Save result</Button>
        </>
      }
    >
      <form id="score-form" className="grid grid-cols-2 gap-4" noValidate onSubmit={(ev) => { ev.preventDefault(); save.mutate() }}>
        <Alert error={save.error} />
        <Input label={`${game.home_name ?? 'Home'} score`} type="number" min={0} value={home} required onChange={(ev) => setHome(ev.target.value)} />
        <Input label={`${game.away_name ?? 'Away'} score`} type="number" min={0} value={away} required onChange={(ev) => setAway(ev.target.value)} />
      </form>
    </Dialog>
  )
}

/** Downloads a game card PDF (LGE-16); failures show as a toast. */
export function CardButton({ game }: { game: Game }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  return (
    <Button
      size="sm"
      variant="secondary"
      loading={busy}
      aria-label={`Print the game card of ${matchup(game)}`}
      onClick={() => {
        setBusy(true)
        downloadFile('/api/v1/games/{game_id}/card', { path: { game_id: game.id } }, 'game-card.pdf')
          .catch((e: Error) => toast('error', e.message))
          .finally(() => setBusy(false))
      }}
    >
      Card
    </Button>
  )
}
