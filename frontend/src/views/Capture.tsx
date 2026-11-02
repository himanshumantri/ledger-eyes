import { useEffect, useState } from 'react'
import { sha256Hex, uploadClip, type Clip } from '../api'
import { whoProblem, type Who } from '../roles'

type Step = 'idle' | 'hashing' | 'uploading' | 'sent' | 'error'

// Hashing reads the whole file into the browser's memory, which a phone may not manage for a big video. The server hashes it anyway.
const BIG_FILE = 150 * 1024 * 1024

const minutes = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`

export default function CaptureView({
  hasPlan, who, clips, onUploaded, onGoToClips,
}: { hasPlan: boolean; who: Who; clips: Clip[]; onUploaded: () => void; onGoToClips: () => void }) {
  const [step, setStep] = useState<Step>('idle')
  const [error, setError] = useState('')
  const [sent, setSent] = useState<Clip | null>(null)
  const [hidden, setHidden] = useState(false)
  const [skippedHash, setSkippedHash] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  // The server reports queued, running and done, not a percentage, so the bar is a moving indicator with the time spent.
  const live = sent ? (clips.find((c) => c.id === sent.id) ?? sent) : null
  const counting = step === 'sent' && live !== null && (live.status === 'queued' || live.status === 'running')
  const finished = step === 'sent' && live !== null && (live.status === 'done' || live.status === 'failed')
  const busy = step === 'hashing' || step === 'uploading'

  useEffect(() => {
    if (!counting) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [counting])

  async function onFile(file: File | undefined) {
    if (!file) return
    const problem = whoProblem(who)
    if (problem) {
      setError(problem)
      setStep('error')
      return
    }
    setError('')
    setSent(null)
    setHidden(false)
    try {
      setStep('hashing')
      const hash = file.size > BIG_FILE ? null : await sha256Hex(file)
      setSkippedHash(hash === null)
      setStep('uploading')
      setSent(await uploadClip(file, hash, who))
      setNow(Date.now())
      setStep('sent')
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStep('error')
    }
  }

  return (
    <section>
      <h2>Capture a shelf</h2>
      {!hasPlan && <p className="warn">The book stock has not been uploaded yet. Ask the auditor to load it.</p>}
      <p className="hint">
        Recorded as the capturer: <strong>{who.name.trim() || '(name missing)'}</strong>, ID <strong>{who.employeeId.trim() || '(missing)'}</strong>. You
        cannot review clips you capture.
      </p>
      <ol className="steps">
        <li>
          Film <strong>one shelf face</strong> per clip, slowly, with the phone held the way it will be reviewed.
        </li>
        <li>
          Say the location first, for example <em>"Aisle A1, shelf B2"</em>, then the item names.
        </li>
        <li>Keep every carton in view and do not cover labels.</li>
        <li>A video can be up to 8 minutes, filmed at 30 frames per second (a phone set to 60 fps reaches the limit in 4 minutes). Film at 720p so a long video stays small enough to upload. Counting takes about one and a half times the length of the video.</li>
      </ol>
      <input
        type="file"
        accept="video/*"
        capture="environment"
        disabled={!hasPlan || busy || counting}
        onChange={(e) => {
          void onFile(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      {step === 'error' && <p className="warn">{error}</p>}
      {step === 'sent' && live && (
        <p role="status">
          Received <strong>{live.original_name}</strong> ({(live.size_bytes / 1e6).toFixed(1)} MB). {skippedHash ? 'The server fingerprint:' : 'The server confirmed the same fingerprint:'}{' '}
          <code>{live.sha256.slice(0, 12)}…</code>.
          {skippedHash && ' The video is large, so the device did not fingerprint it; the server did.'}
        </p>
      )}

      {(busy || ((counting || finished) && !hidden)) && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="Progress">
          <div className="progress-card">
            {busy && (
              <>
                <h3>{step === 'hashing' ? 'Fingerprinting the video…' : 'Uploading…'}</h3>
                <div className="bar" role="progressbar" aria-label="Upload progress">
                  <span />
                </div>
                <p className="hint">Keep this page open until the upload finishes.</p>
              </>
            )}
            {counting && live && (
              <>
                <h3>{live.status === 'queued' ? 'Waiting to start counting…' : 'Counting the cartons…'}</h3>
                <div className="bar" role="progressbar" aria-label="Counting progress">
                  <span />
                </div>
                <p className="hint">
                  {live.original_name} · {minutes(now - new Date(live.uploaded_at).getTime())} so far.
                  {live.duration_seconds ? ` Counting takes about ${minutes(live.duration_seconds * 1000 * 1.5 + 60000)} for a video this long (measured: about 1.4 times its length, plus a minute for the narration).` : ' This can take a minute or two.'}{' '}
                  You can hide this; the count carries on.
                </p>
                <button onClick={() => setHidden(true)}>Hide this</button>
              </>
            )}
            {finished && live && (
              <>
                <h3>{live.status === 'failed' ? 'Counting failed' : 'Counting finished'}</h3>
                <p>
                  {live.status === 'failed'
                    ? live.error
                    : live.needs_review
                      ? 'It needs a reviewer to count it.'
                      : `It counted ${live.machine_count ?? 0} at ${live.location ?? 'an unknown location'}.`}
                </p>
                <button onClick={onGoToClips}>Go to Clips</button> <button onClick={() => setHidden(true)}>Close</button>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
