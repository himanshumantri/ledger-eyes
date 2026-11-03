import { useCallback, useEffect, useRef, useState } from 'react'
import { getClips, getPlan, getReconciliation, type Clip, type Plan, type Row } from './api'
import { BLURB, remember, remembered, ROLES, TABS, whoProblem, type Role } from './roles'
import CaptureView from './views/Capture'
import ClipsView from './views/Clips'
import PlanView from './views/Plan'
import ReconciliationView from './views/Reconciliation'
import Logo from './Logo'

const asRole = (v: string | null): Role => (ROLES.find((r) => r === v) ?? 'Capturer')

export default function App() {
  const [role, setRole] = useState<Role>(() => asRole(remembered('role')))
  const [names, setNames] = useState<Record<Role, string>>(() =>
    Object.fromEntries(ROLES.map((r) => [r, remembered(`name-${r}`) ?? ''])) as Record<Role, string>,
  )
  const [ids, setIds] = useState<Record<Role, string>>(() =>
    Object.fromEntries(ROLES.map((r) => [r, remembered(`employee-id-${r}`) ?? ''])) as Record<Role, string>,
  )
  const [tab, setTab] = useState<string>(TABS[role][0])
  const [plan, setPlan] = useState<Plan | null>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [p, c, r] = await Promise.all([getPlan(), getClips(), getReconciliation()])
      setPlan(p)
      setClips(c)
      setRows(r)
      setError('')
    } catch (e) {
      setError(`Cannot reach the API: ${e instanceof Error ? e.message : String(e)}`)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  // Follow clips that are still being counted.
  const working = clips.some((c) => c.status === 'queued' || c.status === 'running' || c.preview === 'pending')
  const wasWorking = useRef(false)
  useEffect(() => {
    if (!working) {
      // The clip list and the reconciliation are fetched together, so a clip finishing between the two requests leaves the
      // reconciliation one step behind. One more fetch once counting stops catches up.
      if (wasWorking.current) void reload()
      wasWorking.current = false
      return
    }
    wasWorking.current = true
    const t = setInterval(() => void reload(), 3000)
    return () => clearInterval(t)
  }, [working, reload])

  const who = { name: names[role], employeeId: ids[role] }
  const missing = whoProblem(who)
  const waiting = clips.filter((c) => c.status === 'done' && c.needs_review && !c.review).length

  function chooseRole(r: Role) {
    setRole(r)
    setTab(TABS[r][0])
    remember('role', r)
  }

  function rename(value: string) {
    setNames({ ...names, [role]: value })
    remember(`name-${role}`, value)
  }

  function reidentify(value: string) {
    setIds({ ...ids, [role]: value })
    remember(`employee-id-${role}`, value)
  }

  return (
    <>
      <header>
        <h1>LedgerEyes</h1>
        <div className="roles" role="group" aria-label="Viewing as">
          <span>Viewing as</span>
          {ROLES.map((r) => (
            <button key={r} className={r === role ? 'active' : ''} aria-pressed={r === role} onClick={() => chooseRole(r)}>
              {r}
            </button>
          ))}
          <label className="who">
            Name
            <input value={who.name} onChange={(e) => rename(e.target.value)} maxLength={60} aria-invalid={!who.name.trim()} />
          </label>
          <label className="who">
            Employee ID
            <input value={who.employeeId} onChange={(e) => reidentify(e.target.value)} maxLength={40} aria-invalid={!who.employeeId.trim()} />
          </label>
        </div>
        <nav aria-label="Sections">
          {TABS[role].map((t) => (
            <button key={t} className={t === tab ? 'active' : ''} aria-current={t === tab ? 'page' : undefined} onClick={() => setTab(t)}>
              {t}
              {t === 'Clips' && waiting > 0 && role !== 'Capturer' && <span className="badge">{waiting}</span>}
            </button>
          ))}
        </nav>
        <Logo className="brand-mark" />
      </header>
      <main>
        <p className="hint">{BLURB[role]}</p>
        {missing && <p className="warn">{missing}</p>}
        {error && <p className="warn">{error}</p>}
        {tab === 'Book stock' && <PlanView plan={plan} reload={reload} />}
        {tab === 'Capture' && <CaptureView hasPlan={(plan?.lines.length ?? 0) > 0} who={who} clips={clips} onUploaded={reload} onGoToClips={() => setTab('Clips')} />}
        {tab === 'Clips' && plan && <ClipsView clips={clips} plan={plan} role={role} who={who} reload={reload} />}
        {tab === 'Reconciliation' && <ReconciliationView rows={rows} reload={reload} />}
      </main>
    </>
  )
}
