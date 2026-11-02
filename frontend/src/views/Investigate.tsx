import { useEffect, useRef, useState } from 'react'
import {
  API, addClick, drawBox, getInvestigations, patchObject, resolveInvestigation, startInvestigation,
  type Clip, type Investigation, type Plan,
} from '../api'

type Mode = { kind: 'click' } | { kind: 'draw' } | { kind: 'redraw'; id: number }
type Drag = { x0: number; y0: number; x1: number; y1: number }
const MIN_DRAG = 12 // image pixels; a shorter drag is a slip, not a box

/** Work on a clip's frame with SAM: include or exclude proposed cartons, click ones it missed, say which item each is. */
export default function Investigate({ clip, plan, name, onResolved }: { clip: Clip; plan: Plan; name: string; onResolved: () => void }) {
  const [inv, setInv] = useState<Investigation | null>(null)
  const [reviewer, setReviewer] = useState(name)
  const [location, setLocation] = useState(clip.location ?? '')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<Mode | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
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

  const toImage = (e: React.PointerEvent, inv: Investigation) => {
    const r = img.current!.getBoundingClientRect()
    const at = (v: number, size: number, shown: number) => Math.min(size - 1, Math.max(0, Math.round((v / shown) * size)))
    return { x: at(e.clientX - r.left, inv.frame_w, r.width), y: at(e.clientY - r.top, inv.frame_h, r.height) }
  }

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (!mode || !img.current || !inv) return
    const { x, y } = toImage(e, inv)
    if (mode.kind === 'click') {
      setMode(null)
      void run(() => addClick(inv.id, x, y))
      return
    }
    e.currentTarget.setPointerCapture(e.pointerId)
    setDrag({ x0: x, y0: y, x1: x, y1: y })
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!drag || !inv) return
    const { x, y } = toImage(e, inv)
    setDrag({ ...drag, x1: x, y1: y })
  }

  function onPointerUp() {
    if (!drag || !mode || mode.kind === 'click' || !inv) return
    const box: [number, number, number, number] = [Math.min(drag.x0, drag.x1), Math.min(drag.y0, drag.y1), Math.max(drag.x0, drag.x1), Math.max(drag.y0, drag.y1)]
    setDrag(null)
    if (box[2] - box[0] < MIN_DRAG || box[3] - box[1] < MIN_DRAG) {
      setError('Drag a box around the whole carton.')
      return
    }
    const target = mode.kind === 'redraw' ? mode.id : undefined
    setMode(null)
    void run(() => drawBox(inv.id, box, target))
  }

  const instruction =
    mode?.kind === 'click' ? 'Click the carton on the picture.'
    : mode?.kind === 'draw' ? 'Drag a box around the carton on the picture.'
    : mode?.kind === 'redraw' ? `Drag a new box around carton ${mode.id} on the picture.`
    : ''

  return (
    <div className="investigate">
      <h4>Correcting {inv.location ?? 'an unknown location'}</h4>
      <p className="hint">
        Machine count was {inv.machine_count}. Green: counted. Orange, dashed: it was unsure, so it starts excluded. Blue: a carton you added. Use Redraw if its box is wrong.
      </p>
      {inv.capped && <p className="warn">It outlined its maximum of 16 cartons, so more may exist. Draw or click any it missed.</p>}
      <div
        className={`frame${mode ? ' placing' : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => setDrag(null)}
      >
        <img ref={img} src={`${API}/investigations/${inv.id}/frame`} alt="The clip's frame with the proposed cartons outlined" />
        <svg viewBox={`0 0 ${inv.frame_w} ${inv.frame_h}`} preserveAspectRatio="none" aria-hidden="true">
          {inv.objects.map((o) => (
            <g key={o.id} className={`obj ${o.source} ${o.included ? 'in' : 'out'}${o.included && o.conf < 0.8 ? ' weak' : ''}${mode?.kind === 'redraw' && mode.id === o.id ? ' target' : ''}`}>
              <rect x={o.box[0]} y={o.box[1]} width={o.box[2] - o.box[0]} height={o.box[3] - o.box[1]} />
              <text x={o.box[0] + 6} y={o.box[1] + 22}>{o.id}</text>
            </g>
          ))}
          {drag && (
            <rect
              className="draft"
              x={Math.min(drag.x0, drag.x1)}
              y={Math.min(drag.y0, drag.y1)}
              width={Math.abs(drag.x1 - drag.x0)}
              height={Math.abs(drag.y1 - drag.y0)}
            />
          )}
        </svg>
      </div>
      {open && (
        <p>
          {mode ? (
            <>
              {instruction}{' '}
              <button onClick={() => { setMode(null); setDrag(null) }}>Cancel</button>
            </>
          ) : (
            <>
              <button disabled={busy} onClick={() => { setError(''); setMode({ kind: 'draw' }) }}>Draw a carton it missed</button>{' '}
              <button disabled={busy} onClick={() => { setError(''); setMode({ kind: 'click' }) }}>Click a carton it missed</button>
            </>
          )}
        </p>
      )}
      {error && <p className="warn">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Count it</th>
            <th>Item</th>
            <th className="num">Confidence</th>
            <th>Box</th>
          </tr>
        </thead>
        <tbody>
          {inv.objects.map((o) => (
            <tr key={o.id}>
              <td>{o.id}{o.source === 'click' ? ' (clicked)' : o.source === 'drawn' ? ' (drawn)' : o.adjusted ? ' (redrawn)' : ''}</td>
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
              <td>
                <button disabled={!open || busy || !!mode} onClick={() => { setError(''); setMode({ kind: 'redraw', id: o.id }) }}>
                  Redraw
                </button>
              </td>
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
