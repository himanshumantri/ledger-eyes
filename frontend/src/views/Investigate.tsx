import { useEffect, useRef, useState } from 'react'
import {
  API, addClick, getInvestigations, patchObject, resolveInvestigation, startInvestigation,
  type Clip, type Investigation, type Plan,
} from '../api'

/** Work on a clip's frame with SAM: include or exclude proposed cartons, click ones it missed, say which item each is. */
export default function Investigate({ clip, plan, name, onResolved }: { clip: Clip; plan: Plan; name: string; onResolved: () => void }) {
  const [inv, setInv] = useState<Investigation | null>(null)
  const [reviewer, setReviewer] = useState(name)
  const [location, setLocation] = useState(clip.location ?? '')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [placing, setPlacing] = useState(false)
  const img = useRef<HTMLImageElement>(null)

  useEffect(() => {
    let live = true
    getInvestigations(clip.id)
      .then((all) => live && setInv(all.find((i) => i.status === 'open') ?? null))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [clip.id])

  async function run(action: () => Promise<Investigation>, after?: () => void) {
    setBusy(true)
    setError('')
    try {
      setInv(await action())
      after?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!inv) {
    return (
      <div className="review">
        <h4>Correct real footage</h4>
        <p className="hint">It proposes the cartons on this clip's frame. You include or exclude each one, click any it missed, and say which item each is.</p>
        {!clip.location && (
          <label>
            Location
            <select value={location} onChange={(e) => setLocation(e.target.value)}>
              <option value="">Choose…</option>
              {plan.locations.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </label>
        )}
        <label>
          Reviewer
          <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </label>
        {error && <p className="warn">{error}</p>}
        <button
          disabled={busy || !reviewer.trim()}
          onClick={() => void run(() => startInvestigation(clip.id, reviewer.trim(), clip.location ? undefined : location || undefined))}
        >
          {busy ? 'Looking at the frame…' : 'Start'}
        </button>
      </div>
    )
  }

  const items = [...new Set(plan.lines.filter((l) => !inv.location || l.location === inv.location).map((l) => l.item))]
  const book = (item: string) => plan.lines.find((l) => l.location === inv.location && l.item === item)?.book_qty ?? 0
  const shown = [...new Set([...items, ...Object.keys(inv.counts.per_item)])]
  const open = inv.status === 'open'

  function onImageClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!placing || !img.current || !inv) return
    const r = img.current.getBoundingClientRect()
    const x = Math.round(((e.clientX - r.left) / r.width) * inv.frame_w)
    const y = Math.round(((e.clientY - r.top) / r.height) * inv.frame_h)
    setPlacing(false)
    void run(() => addClick(inv.id, x, y))
  }

  return (
    <div className="investigate">
      <h4>Correcting {inv.location ?? 'an unknown location'}</h4>
      <p className="hint">
        Machine count was {inv.machine_count}. Green: counted. Orange, dashed: it was unsure, so it starts excluded. Blue: you clicked it.
      </p>
      {inv.capped && <p className="warn">It outlined its maximum of 16 cartons, so more may exist. Click any it missed.</p>}
      <div className={`frame${placing ? ' placing' : ''}`} onClick={onImageClick}>
        <img ref={img} src={`${API}/investigations/${inv.id}/frame`} alt="The clip's frame with the proposed cartons outlined" />
        <svg viewBox={`0 0 ${inv.frame_w} ${inv.frame_h}`} preserveAspectRatio="none" aria-hidden="true">
          {inv.objects.map((o) => (
            <g key={o.id} className={`obj ${o.source} ${o.included ? 'in' : 'out'}${o.included && o.conf < 0.8 ? ' weak' : ''}`}>
              <rect x={o.box[0]} y={o.box[1]} width={o.box[2] - o.box[0]} height={o.box[3] - o.box[1]} />
              <text x={o.box[0] + 6} y={o.box[1] + 22}>{o.id}</text>
            </g>
          ))}
        </svg>
      </div>
      {open && (
        <p>
          <button disabled={busy} onClick={() => setPlacing(!placing)}>
            {placing ? 'Click the carton on the picture… (cancel)' : 'Add a carton it missed'}
          </button>
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Count it</th>
            <th>Item</th>
            <th className="num">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {inv.objects.map((o) => (
            <tr key={o.id}>
              <td>{o.id}{o.source === 'click' ? ' (clicked)' : ''}</td>
              <td>
                <input
                  type="checkbox"
                  checked={o.included}
                  disabled={!open || busy}
                  aria-label={`Count carton ${o.id}`}
                  onChange={(e) => void run(() => patchObject(inv.id, o.id, { included: e.target.checked }))}
                />
              </td>
              <td>
                <select
                  value={o.item ?? ''}
                  disabled={!open || busy}
                  aria-label={`Item for carton ${o.id}`}
                  onChange={(e) => void run(() => patchObject(inv.id, o.id, { item: e.target.value }))}
                >
                  <option value="">Which item?</option>
                  {items.map((i) => (
                    <option key={i}>{i}</option>
                  ))}
                </select>
              </td>
              <td className="num">{o.conf.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th className="num">Book</th>
            <th className="num">Your count</th>
            <th className="num">Difference</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((item) => {
            const n = inv.counts.per_item[item] ?? 0
            return (
              <tr key={item}>
                <td>{item}</td>
                <td className="num">{book(item)}</td>
                <td className="num">{n}</td>
                <td className="num">{n - book(item) > 0 ? '+' : ''}{n - book(item)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {inv.counts.unassigned > 0 && <p className="warn">{inv.counts.unassigned} counted carton(s) still need an item.</p>}
      <p className="hint">This is what is visible in this one picture. Cartons hidden behind others are not counted.</p>
      {open && (
        <div className="review">
          <label>
            Note (kept with the decision)
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          {error && <p className="warn">{error}</p>}
          <p>
            <button disabled={busy} onClick={() => void run(() => resolveInvestigation(inv.id, 'confirmed', note), onResolved)}>
              Confirm this count
            </button>{' '}
            <button disabled={busy} onClick={() => void run(() => resolveInvestigation(inv.id, 'unresolved', note), onResolved)}>
              Leave unresolved
            </button>
          </p>
        </div>
      )}
      {!open && <p>Resolved as {inv.outcome}{inv.note ? `: ${inv.note}` : ''}.</p>}
      <details>
        <summary>What was done ({inv.events.length} steps)</summary>
        <ul>
          {inv.events.map((e, i) => (
            <li key={i}>
              {new Date(e.at).toLocaleTimeString()} · {e.actor} · {e.action.replace('_', ' ')} {JSON.stringify(e.detail)}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}
