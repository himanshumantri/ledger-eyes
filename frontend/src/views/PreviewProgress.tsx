import type { Clip } from '../api'

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds) % 60).padStart(2, '0')}`

/** What the playable copy of a video is doing: a bar with a real percentage while it is made, the reason if it could not be. */
export default function PreviewProgress({ clip }: { clip: Clip }) {
  if (clip.preview === 'failed') {
    return (
      <p className="warn">
        The video could not be prepared for pausing: {clip.preview_error ?? 'no reason was given'}. You can still start from the frame it picked.
      </p>
    )
  }
  if (clip.preview !== 'pending') return null
  const percent = clip.preview_progress
  const started = clip.finished_at ? new Date(clip.finished_at).getTime() : null
  // The copy is started the moment counting finishes, so time since then and the percentage done give a rough time left.
  const left = percent && percent >= 5 && started ? ` About ${clock(((Date.now() - started) / 1000) * ((100 - percent) / percent))} left.` : ''
  return (
    <div className="prep" role="status">
      <p>
        <strong>Preparing the video so you can pause it on a moment{percent !== null ? `: ${percent}%` : ''}.</strong>
        {left}
      </p>
      <div className={`bar${percent !== null ? ' known' : ''}`} role="progressbar" aria-label="Preparing the video" aria-valuenow={percent ?? undefined} aria-valuemin={0} aria-valuemax={100}>
        <span style={percent !== null ? { width: `${percent}%` } : undefined} />
      </div>
    </div>
  )
}
