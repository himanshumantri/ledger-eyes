import { useEffect, useRef, useState } from 'react'
import {
  API, deleteObject, drawBox, getInvestigations, patchObject, previewUrl, resolveInvestigation, startFromFrame, startInvestigation,
  type Clip, type Corner, type InvObject, type Investigation, type Plan,
} from '../api'
import { whoProblem, type Who } from '../roles'
import { bringIntoView } from '../scroll'
import PreviewProgress from './PreviewProgress'

type Mode = { kind: 'add' } | { kind: 'redraw'; id: number }
const MIN_SIDE = 12 // image pixels; corners closer than this are a slip, not a carton

/** Work on a clip's frame: include or exclude proposed cartons, redraw or delete a wrong one, add one it missed, say which item each is. */
export default function Investigate({ clip, plan, who, onResolved }: { clip: Clip; plan: Plan; who: Who; onResolved: () => void }) {
  const [inv, setInv] = useState<Investigation | null>(null)
  const [location, setLocation] = useState(clip.location ?? '')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<Mode | null>(null)
  const [corners, setCorners] = useState<Corner[]>([]) // the top-left corner, then the bottom-right one
  const [hover, setHover] = useState<Corner | null>(null)
  const img = useRef<HTMLImageElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const [at, setAt] = useState(0) // seconds into the video where it is paused
  const top = useRef<HTMLDivElement>(null)
  const [cancelled, setCancelled] = useState(false)

  // When the working view opens (the frame and its boxes are taller than the start screen), bring it to the top of the screen.
  useEffect(() => {
    if (inv?.id) bringIntoView(top.current)
  }, [inv?.id])

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

  /** Take the exact frame the video is paused on and start from it. */
  async function useThisFrame() {
    const v = video.current
    if (!v || !v.videoWidth) {
      setError('Play the video, then pause it on the moment you want to correct.')
      return
    }
    v.pause()
    await run(async () => {
      let image: Blob | null = null
      try {
        const canvas = document.createElement('canvas')
        canvas.width = v.videoWidth
        canvas.height = v.videoHeight
        canvas.getContext('2d')?.drawImage(v, 0, 0)
        image = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
      } catch {
        image = null
      }
      if (!image) throw new Error('The browser would not let this page take the picture. Use the frame it picked instead.')
      return startFromFrame(clip.id, image, Math.round(v.currentTime * 1000), who, clip.location ? undefined : location || undefined)
    })
  }

  /** Drop this attempt and go back to choosing a frame. Nothing is counted; the log keeps that it was cancelled. */
  async function cancel() {
    if (!inv) return
    if (inv.events.length > 1 && !window.confirm('Cancel and go back? What you changed in this session will not be counted. The clip keeps the count it had before.')) return
    setBusy(true)
    setError('')
    try {
      await resolveInvestigation(inv.id, 'unresolved', 'Cancelled by the reviewer')
      setInv(null)
      setMode(null)
      setCorners([])
      setNote('')
      setCancelled(true)
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
    setHover(null)
  }

  if (!inv) {
    const problem = whoProblem(who)
    return (
      <div className="review">
        <h4>Correct real footage</h4>
        {cancelled && <p className="hint">Cancelled. Nothing was changed: the clip keeps the count it had before. Pick a frame to start again.</p>}
        {clip.preview === 'ready' ? (
          <>
            <p className="hint">
              Play the video and pause it on the moment you want to correct, then press Use this frame. It will outline the cartons on that exact
              picture. Paused at <strong>{Math.floor(at / 60)}:{String(Math.floor(at) % 60).padStart(2, '0')}</strong>.
            </p>
            <video
              ref={video}
              className="clipvideo"
              src={previewUrl(clip.id)}
              controls
              playsInline
              preload="metadata"
              crossOrigin="anonymous"
              onTimeUpdate={(e) => setAt(e.currentTarget.currentTime)}
              onSeeked={(e) => setAt(e.currentTarget.currentTime)}
            />
          </>
        ) : (
          <p className="hint">
            It proposes the cartons on this clip's frame. You include or exclude each one, redraw or delete a wrong box, add any it missed, and say which
            item each is.
          </p>
        )}
        <PreviewProgress clip={clip} />
        {clip.preview === 'pending' && (
          <p className="hint">Wait for the video if you want to pause on a moment you choose. The button below starts now, on the one frame it picked.</p>
        )}
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
        {clip.preview === 'ready' && (
          <>
            <button className="primary" disabled={busy || !!problem} onClick={() => void useThisFrame()}>
              {busy ? 'Looking at the frame…' : 'Use this frame'}
            </button>{' '}
          </>
        )}
        <button
          disabled={busy || !!problem}
          onClick={() => void run(() => startInvestigation(clip.id, who.name.trim(), who.employeeId.trim(), clip.location ? undefined : location || undefined))}
        >
          {busy ? 'Looking at the frame…' : clip.preview === 'ready' || clip.preview === 'pending' ? 'Use the frame it picked' : 'Start'}
        </button>
      </div>
    )
  }

  const items = [...new Set(plan.lines.filter((l) => !inv.location || l.location === inv.location).map((l) => l.item))]
  const book = (item: string) => plan.lines.find((l) => l.location === inv.location && l.item === item)?.book_qty ?? 0
  const shown = [...new Set([...items, ...Object.keys(inv.counts.per_item)])]
  const open = inv.status === 'open'
  const marked = (o: InvObject) => o.source !== 'auto' || !!o.adjusted // a box the reviewer drew: its confidence is not meaningful

  function toImage(e: React.PointerEvent<HTMLDivElement>): Corner | null {
    if (!img.current || !inv) return null
    const r = img.current.getBoundingClientRect()
    const at = (v: number, size: number, shownSize: number) => Math.min(size - 1, Math.max(0, Math.round((v / shownSize) * size)))
    return { x: at(e.clientX - r.left, inv.frame_w, r.width), y: at(e.clientY - r.top, inv.frame_h, r.height) }
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (mode && corners.length === 1) setHover(toImage(e))
  }

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    const point = toImage(e)
    if (!mode || !point || !inv || busy) return
    if (corners.length === 0) {
      setCorners([point])
      return
    }
    // Two corners in: the box between them goes to SAM, which outlines the carton inside it.
    const both = [corners[0], point]
    const box: [number, number, number, number] = [
      Math.min(both[0].x, both[1].x), Math.min(both[0].y, both[1].y), Math.max(both[0].x, both[1].x), Math.max(both[0].y, both[1].y),
    ]
    if (box[2] - box[0] < MIN_SIDE || box[3] - box[1] < MIN_SIDE) {
      setCorners([])
      setHover(null)
      setError('Those two corners are too close together. Click the top-left and then the bottom-right corner of the carton.')
      return
    }
    const target = mode.kind === 'redraw' ? mode.id : undefined
    stop()
    void run(() => drawBox(inv.id, box, both, target))
  }

  const instruction = `${mode?.kind === 'redraw' ? `Redrawing carton ${mode.id}. ` : ''}${corners.length === 0 ? 'Click the top-left corner of the carton.' : 'Now click the bottom-right corner.'}`
  const preview =
    corners.length === 1 && hover
      ? { x: Math.min(corners[0].x, hover.x), y: Math.min(corners[0].y, hover.y), w: Math.abs(hover.x - corners[0].x), h: Math.abs(hover.y - corners[0].y) }
      : null

  return (
    <div className="investigate" ref={top}>
      <div className="panel-head">
        <h4>Correcting {inv.location ?? 'an unknown location'}</h4>
        {open && (
          <button className="btn-red" disabled={busy} onClick={() => void cancel()}>
            Cancel
          </button>
        )}
      </div>
      <p className="hint">
        It confirmed {inv.machine_count} on its own. Green: counted. Red, dashed: it was unsure, so it starts excluded. Dark outline: a carton you added.
        Use Redraw if a box is wrong and Delete if it is not a carton at all.
      </p>
      {inv.capped && <p className="warn">It outlined its maximum of 16 cartons, so more may exist. Add any it missed.</p>}
      <div className={`frame${mode ? ' placing' : ''}`} onPointerDown={onPointerDown} onPointerMove={onPointerMove}>
        <img ref={img} src={`${API}/investigations/${inv.id}/frame`} alt="The clip's frame with the proposed cartons outlined" />
        <svg viewBox={`0 0 ${inv.frame_w} ${inv.frame_h}`} preserveAspectRatio="none" aria-hidden="true">
          {inv.objects.map((o) => (
            <g key={o.id} className={`obj ${o.source} ${o.included ? 'in' : 'out'}${o.included && o.conf < 0.8 && !marked(o) ? ' weak' : ''}${mode?.kind === 'redraw' && mode.id === o.id ? ' target' : ''}`}>
              <rect x={o.box[0]} y={o.box[1]} width={o.box[2] - o.box[0]} height={o.box[3] - o.box[1]} />
              <text x={o.box[0] + 6} y={o.box[1] + 22}>{o.id}</text>
            </g>
          ))}
          {preview && <rect className="draft" x={preview.x} y={preview.y} width={preview.w} height={preview.h} />}
          {corners.map((c, i) => (
            <circle key={i} className="vertex" cx={c.x} cy={c.y} r={9} />
          ))}
        </svg>
      </div>
      {open && (
        <p>
          {mode ? (
            <>
              {instruction}{' '}
              {corners.length > 0 && <button onClick={() => { setCorners([]); setHover(null) }}>Undo corner</button>}{' '}
              <button onClick={stop}>Cancel marking</button>
            </>
          ) : (
            <>
              <button className="btn-slate" disabled={busy} onClick={() => begin({ kind: 'add' })}>Add a carton</button>
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
              <td className="num">{marked(o) ? 'you marked it' : o.conf.toFixed(2)}</td>
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
      <p className="hint">Mark only the part you can see. Count a carton if more than half of it is visible. Cartons hidden behind others are not counted.</p>
      {open && (
        <div className="review">
          <label>
            Note (kept with the decision)
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <p>
            <button className="btn-green" disabled={busy} onClick={() => void run(() => resolveInvestigation(inv.id, 'confirmed', note), onResolved)}>
              Confirm this count
            </button>{' '}
            <button className="btn-amber" disabled={busy} onClick={() => void run(() => resolveInvestigation(inv.id, 'unresolved', note), onResolved)}>
              Leave unresolved
            </button>{' '}
            <button className="btn-red" disabled={busy} onClick={() => void cancel()}>
              Cancel
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
