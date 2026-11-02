import { useState } from 'react'
import { API, type Clip, type Plan } from '../api'
import { plain } from '../plain'
import type { Role } from '../roles'
import Investigate from './Investigate'
import ReviewForm from './ReviewForm'

function statusLabel(c: Clip): { text: string; tone: string } {
  if (c.status === 'failed') return { text: 'Failed', tone: 'bad' }
  if (c.status !== 'done') return { text: c.status === 'queued' ? 'Queued' : 'Counting…', tone: 'wait' }
  if (c.review) return { text: 'Reviewed', tone: 'ok' }
  return c.needs_review ? { text: 'Needs review', tone: 'warn' } : { text: 'Auto-passed', tone: 'ok' }
}

export default function ClipsView({ clips, plan, role, name, reload }: { clips: Clip[]; plan: Plan; role: Role; name: string; reload: () => void }) {
  const [open, setOpen] = useState<string | null>(null)
  const queue = clips.filter((c) => c.status === 'done' && c.needs_review && !c.review).length

  return (
    <section>
      <h2>Clips</h2>
      <p className="hint">
        {role === 'Capturer'
          ? 'Your uploads and what happened to them.'
          : queue > 0
            ? `${queue} clip(s) need a reviewer's count before they reach the reconciliation.`
            : 'Nothing waiting for review.'}
      </p>
      {clips.length === 0 && <p>No clips yet.</p>}
      <ul className="clips">
        {clips.map((c) => {
          const st = statusLabel(c)
          const isOpen = open === c.id
          return (
            <li key={c.id}>
              <button className="row" onClick={() => setOpen(isOpen ? null : c.id)} aria-expanded={isOpen}>
                <span className="name">{c.original_name}</span>
                <span>{c.location ?? 'location unknown'}</span>
                <span className="num">
                  {c.review ? c.review.lines.reduce((n, l) => n + l.qty, 0) : c.needs_review ? '–' : (c.machine_count ?? '–')}
                </span>
                <span className={`tag ${st.tone}`}>{st.text}</span>
              </button>
              {isOpen && (
                <div className="detail">
                  {c.status === 'failed' && <p className="warn">{plain(c.error)}</p>}
                  {c.reasons.length > 0 && (
                    <ul>
                      {c.reasons.map((r) => (
                        <li key={r}>{plain(r)}</li>
                      ))}
                    </ul>
                  )}
                  {c.status === 'done' && c.needs_review && !c.review && (
                    <p className="hint">
                      Not counted yet. Cartons it could not confirm are left out, so a reviewer's count is needed
                      {c.machine_count ? ` (it confirmed ${c.machine_count} on its own)` : ''}.
                    </p>
                  )}
                  {c.transcript && <p className="hint">Narration: “{c.transcript}”</p>}
                  <p className="hint">
                    Fingerprint <code>{c.sha256.slice(0, 16)}…</code> · received {new Date(c.uploaded_at).toLocaleString()}
                  </p>
                  {c.has_evidence && (
                    <figure>
                      <img src={`${API}/clips/${c.id}/evidence`} alt="Evidence frame with the counted cartons outlined" />
                      <figcaption>
                        <ul className="legend">
                          <li>
                            <i className="swatch" style={{ background: '#2e9e4f' }} /> Green: outlined and confirmed, so it is counted.
                          </li>
                          <li>
                            <i className="swatch" style={{ background: '#f58231' }} /> Orange: outlined, but it could not confirm it. Not counted.
                          </li>
                          <li>
                            <i className="swatch" style={{ background: '#1f6feb' }} /> Blue ?: a carton it sees but has not outlined. Not counted.
                          </li>
                        </ul>
                      </figcaption>
                    </figure>
                  )}
                  {c.review && (
                    <p>
                      Reviewed by {c.review.reviewer}: {c.review.lines.map((l) => `${l.item} ${l.qty}`).join(', ')}
                    </p>
                  )}
                  {c.status === 'done' && role === 'Auditor' && (
                    <details className="inv">
                      <summary>Correct real footage</summary>
                      <Investigate key={`${c.id}-${name}`} clip={c} plan={plan} name={name} onResolved={reload} />
                    </details>
                  )}
                  {c.status === 'done' && role === 'Reviewer' && (
                    <ReviewForm key={`${c.id}-${name}-${c.review?.created_at ?? 'new'}`} clip={c} plan={plan} name={name} onSaved={reload} />
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
