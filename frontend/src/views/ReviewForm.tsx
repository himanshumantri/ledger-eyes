import { useState } from 'react'
import { postReview, type Clip, type Plan } from '../api'
import { whoProblem, type Who } from '../roles'

/** A reviewer's per-item counts for one clip. Submitting replaces the machine count for the clip. */
export default function ReviewForm({ clip, plan, who, onSaved }: { clip: Clip; plan: Plan; who: Who; onSaved: () => void }) {
  const [location, setLocation] = useState(clip.location ?? '')
  const [qty, setQty] = useState<Record<string, string>>(
    Object.fromEntries((clip.review?.lines ?? []).map((l) => [l.item, String(l.qty)])),
  )
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const items = [...new Set(plan.lines.filter((l) => !location || l.location === location).map((l) => l.item))]

  async function save() {
    const lines = items.filter((i) => qty[i] !== undefined && qty[i] !== '').map((i) => ({ item: i, qty: Number(qty[i]), note: '' }))
    const problem = whoProblem(who)
    if (problem) return setError(problem)
    if (!clip.location && !location) return setError('Choose the location: the narration did not name one.')
    if (lines.length === 0 || lines.some((l) => !Number.isInteger(l.qty) || l.qty < 0)) return setError('Enter a whole number for at least one item.')
    setSaving(true)
    setError('')
    try {
      await postReview(clip.id, { reviewer: who.name.trim(), reviewer_id: who.employeeId.trim(), location: clip.location ? undefined : location, lines })
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      className="review"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <h4>{clip.review ? 'Change the review' : 'Your count'}</h4>
      <p className="hint">
        Count each carton that is more than half visible. It confirmed {clip.machine_count} on its own. Leave an item blank if none are on this shelf.
      </p>
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
      <div className="qty-grid">
        {items.map((item) => (
          <label key={item}>
            {item}
            <input className="qty" type="number" min={0} step={1} value={qty[item] ?? ''} onChange={(e) => setQty({ ...qty, [item]: e.target.value })} />
          </label>
        ))}
      </div>
      <p className="hint">
        Recorded as {who.name.trim() || '(name missing)'}, ID {who.employeeId.trim() || '(missing)'}.
      </p>
      {error && <p className="warn">{error}</p>}
      <button type="submit" className="primary" disabled={saving}>
        {saving ? 'Saving…' : 'Save count'}
      </button>
    </form>
  )
}
