import { useEffect, useRef, useState } from 'react'
import {
  API, addClick, deleteObject, drawBox, getInvestigations, patchObject, resolveInvestigation, startInvestigation,
  type Clip, type Corner, type Investigation, type Plan,
} from '../api'
import { whoProblem, type Who } from '../roles'

type Mode = { kind: 'click' } | { kind: 'draw' } | { kind: 'redraw'; id: number }
const MIN_SIDE = 12 // image pixels; corners closer than this are a slip, not a carton
const CORNER_WORDS = ['first', 'second', 'third', 'fourth']

/** Work on a clip's frame: include or exclude proposed cartons, redraw or delete a wrong one, add one it missed, say which item each is. */
export default function Investigate({ clip, plan, who, onResolved }: { clip: Clip; plan: Plan; who: Who; onResolved: () => void }) {
  const [inv, setInv] = useState<Investigation | null>(null)
  const [location, setLocation] = useState(clip.location ?? '')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<Mode | null>(null)
  const [corners, setCorners] = useState<Corner[]>([])
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

  function begin(next: Mode) {
    setError('')
    setCorners([])
    setMode(next)
  }

  function stop() {
    setMode(null)
    setCorners([])
  }

  if (!inv) {
    const problem = whoProblem(who)
    return (
      <div className="review">
        <h4>Correct real footage</h4>
        <p className="hint">It proposes the cartons on this clip's frame. You include or exclude each one, redraw or delete a wrong box, add any it missed, and say which item each is.</p>
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
        <p className="hint">
          Recorded as {who.name.trim() || '(name missing)'}, ID {who.employeeId.trim() || '(missing)'}.
        </p>
        {(problem || error) && <p className="warn">{problem || error}</p>}
        <button
          disabled={busy || !!problem}
          onClick={() => void run(() => startInvestigation(clip.id, who.name.trim(), who.employeeId.trim(), clip.location ? undefined : location || undefined))}
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

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (!mode || !img.current || !inv || busy) return
    const r = img.current.getBoundingClientRect()
    const at = (v: number, size: number, shownSize: number) => Math.min(size - 1, Math.max(0, Math.round((v / shownSize) * size)))
    const point = { x: at(e.clientX - r.left, inv.frame_w, r.width), y: at(e.clientY - r.top, inv.frame_h, r.height) }
    if (mode.kind === 'click') {
      stop()
      void run(() => addClick(inv.id, point.x, point.y))
      return
    }
    const next = [...corners, point]
    if (next.length < 4) {
      setCorners(next)
      return
    }
    // Four corners in: the box that holds them goes to SAM, which outlines the carton inside it.
    const xs = next.map((c) => c.x)
    const ys = next.map((c) => c.y)
    const box: [number, number, number, number] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
    if (box[2] - box[0] < MIN_SIDE || box[3] - box[1] < MIN_SIDE) {
      setCorners([])
      setError('Those corners are too close together. Click the four corners of the whole carton.')
      return
    }
    const target = mode.kind === 'redraw' ? mode.id : undefined
    stop()
    void run(() => drawBox(inv.id, box, next, target))
  }

  const instruction =
    mode?.kind === 'click'
      ? 'Click the carton on the picture.'
      : mode
        ? `${mode.kind === 'redraw' ? `Redrawing carton ${mode.id}: ` : ''}click the ${CORNER_WORDS[corners.length]} corner of the carton (${corners.length} of 4 placed).`
        : ''

  return (
    <div className="investigate">
      <h4>Correcting {inv.location ?? 'an unknown location'}</h4>
      <p className="hint">
        It confirmed {inv.machine_count} on its own. Green: counted. Orange, dashed: it was unsure, so it starts excluded. Blue: a carton you added.
        Use Redraw if a box is wrong and Delete if it is not a carton at all.
      </p>
      {inv.capped && <p className="warn">It outlined its maximum of 16 cartons, so more may exist. Add any it missed.</p>}
      <div className={`frame${mode ? ' placing' : ''}`} onPointerDown={onPointerDown}>
        <img ref={img} src={`${API}/investigations/${inv.id}/frame`} alt="The clip's frame with the proposed cartons outlined" />
        <svg viewBox={`0 0 ${inv.frame_w} ${inv.frame_h}`} preserveAspectRatio="none" aria-hidden="true">
          {inv.objects.map((o) => (
            <g key={o.id} className={`obj ${o.source} ${o.included ? 'in' : 'out'}${o.included && o.conf < 0.8 ? ' weak' : ''}${mode?.kind === 'redraw' && mode.id === o.id ? ' target' : ''}`}>
              <rect x={o.box[0]} y={o.box[1]} width={o.box[2] - o.box[0]} height={o.box[3] - o.box[1]} />
              <text x={o.box[0] + 6} y={o.box[1] + 22}>{o.id}</text>
            </g>
          ))}
          {corners.length > 1 && <polyline className="draft" points={corners.map((c) => `${c.x},${c.y}`).join(' ')} />}
          {corners.length === 4 && <polygon className="draft" points={corners.map((c) => `${c.x},${c.y}`).join(' ')} />}
          {corners.map((c, i) => (
            <g key={i} className="vertex">
              <circle cx={c.x} cy={c.y} r={9} />
              <text x={c.x + 12} y={c.y - 8}>{i + 1}</text>
            </g>
          ))}
        </svg>
      </div>
      {open && (
        <p>
          {mode ? (
            <>
              {instruction}{' '}
              {corners.length > 0 && <button onClick={() => setCorners(corners.slice(0, -1))}>Undo last corner</button>}{' '}
              <button onClick={stop}>Cancel</button>
            </>
          ) : (
            <>
              <button disabled={busy} onClick={() => begin({ kind: 'draw' })}>Add a carton: click its 4 corners</button>{' '}
              <button disabled={busy} onClick={() => begin({ kind: 'click' })}>Add a carton: click its middle</button>
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
              <td>{o.id}{o.source === 'click' ? ' (clicked)' : o.source === 'drawn' ? ' (added)' : o.adjusted ? ' (redrawn)' : ''}</td>
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
              <td className="actions">
                <button disabled={!open || busy || !!mode} onClick={() => begin({ kind: 'redraw', id: o.id })}>
                  Redraw
                </button>{' '}
                <button
                  className="danger"
                  disabled={!open || busy || !!mode}
                  aria-label={`Delete box ${o.id}`}
                  onClick={() => {
                    if (window.confirm(`Delete box ${o.id}? Use the tick box instead if you only want to leave it out of the count.`)) void run(() => deleteObject(inv.id, o.id))
                  }}
                >
                  Delete
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
