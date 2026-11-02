/** Demo roles. There is no login yet: choosing a role only changes what the screen shows and who the actions are recorded as. */
export const ROLES = ['Capturer', 'Reviewer', 'Auditor'] as const
export type Role = (typeof ROLES)[number]

export const TABS: Record<Role, readonly string[]> = {
  Capturer: ['Capture', 'Clips'],
  Reviewer: ['Clips'],
  Auditor: ['Reconciliation', 'Clips', 'Book stock'],
}

export const BLURB: Record<Role, string> = {
  Capturer: 'Films each shelf and uploads it. Cannot review their own clips.',
  Reviewer: 'Counts the clips it flagged, and corrects its boxes on the real footage so the counts match the stockroom.',
  Auditor: 'Compares the counts with the books and follows each variance back to who counted it and the evidence.',
}

export const DEFAULT_NAME: Record<Role, string> = { Capturer: 'Capturer', Reviewer: 'Reviewer', Auditor: 'Auditor' }

export function remembered(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null // storage can be blocked; the page works without it
  }
}

export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* ignore */
  }
}
