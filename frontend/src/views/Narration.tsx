import { useEffect, useId, useRef, useState } from 'react'

const LINES = 2

/** The spoken narration, cut to two lines with a button to read the rest, which slides open below. */
export default function Narration({ text }: { text: string }) {
  const id = useId()
  const body = useRef<HTMLParagraphElement>(null)
  const [open, setOpen] = useState(false)
  const [long, setLong] = useState(false)
  const [full, setFull] = useState(0) // height of the whole text, so the slide has a number to animate to

  useEffect(() => {
    const measure = () => {
      const el = body.current
      if (!el) return
      const line = parseFloat(getComputedStyle(el).lineHeight)
      setFull(el.scrollHeight)
      setLong(el.scrollHeight > line * LINES + 1)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [text])

  return (
    <div className="narration">
      <p
        ref={body}
        id={id}
        className="hint"
        style={{ maxHeight: long && !open ? `${LINES * 1.5}em` : full ? `${full}px` : undefined }}
      >
        Narration: “{text}”
      </p>
      {long && (
        <button className="link" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
          {open ? 'Show less' : 'Continue reading'}
        </button>
      )}
    </div>
  )
}
