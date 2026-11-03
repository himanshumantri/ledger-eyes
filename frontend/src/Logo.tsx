/** The mark: an open ledger with an eye on each page, Debit on the left and Credit on the right. Drawn inline so the
 * labels use the page's own font. Slate cover, so it stands out on the dark header. */
export default function Logo({ className }: { className?: string }) {
  const label = {
    fontFamily: 'var(--font)', fontWeight: 700, fontSize: 25, textAnchor: 'middle' as const, fill: '#1e293b',
    stroke: '#f5f7f9', strokeWidth: 6, paintOrder: 'stroke', strokeLinejoin: 'round' as const,
  }
  return (
    <svg className={className} viewBox="0 0 320 200" role="img" aria-label="LedgerEyes: an open ledger with an eye on each page, Debit on the left and Credit on the right">
      <defs>
        <clipPath id="logo-left">
          <path d="M160 40 C120 28 60 28 20 44 L20 166 C60 150 120 150 160 166 Z" />
        </clipPath>
        <g id="logo-leftpage">
          <path d="M160 40 C120 28 60 28 20 44 L20 166 C60 150 120 150 160 166 Z" fill="#f5f7f9" />
          <g clipPath="url(#logo-left)" stroke="#64748b" strokeWidth="2.2" fill="none" strokeLinecap="round" opacity="0.55">
            <path id="logo-line" d="M28 52 C64 37 116 37 152 48" />
            {[22, 44, 66, 88, 110].map((y) => (
              <use key={y} href="#logo-line" y={y} />
            ))}
            <path d="M118 20 V170" />
          </g>
          <path d="M42 106 C58 76 122 76 138 106 C122 136 58 136 42 106 Z" fill="#ffffff" stroke="#1e293b" strokeWidth="5" strokeLinejoin="round" />
          <circle cx="90" cy="106" r="17" fill="#64748b" />
          <circle cx="90" cy="106" r="8" fill="#1e293b" />
          <circle cx="95" cy="101" r="3.4" fill="#ffffff" />
        </g>
      </defs>
      <path d="M10 36 C62 18 120 18 160 32 C200 18 258 18 310 36 L310 178 C258 160 200 160 160 178 C120 160 62 160 10 178 Z" fill="#64748b" />
      <use href="#logo-leftpage" />
      <use href="#logo-leftpage" transform="translate(320 0) scale(-1 1)" />
      <path d="M160 38 V168" stroke="#1e293b" strokeWidth="3.5" strokeLinecap="round" />
      <text x="90" y="72" style={label}>Debit</text>
      <text x="230" y="72" style={label}>Credit</text>
    </svg>
  )
}
