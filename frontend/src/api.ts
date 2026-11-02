import { plain } from './plain'

export const API: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Clip = {
  id: string
  original_name: string
  captured_by: string | null
  captured_by_id: string | null
  sha256: string
  size_bytes: number
  duration_seconds: number | null
  uploaded_at: string
  finished_at: string | null
  status: 'queued' | 'running' | 'done' | 'failed'
  error: string
  location: string | null
  narrated_location: string | null
  item: string | null
  machine_count: number | null
  needs_review: boolean
  reasons: string[]
  has_evidence: boolean
  preview: 'ready' | 'pending' | 'none' // the playable copy of the video
  transcript: string
  review: { reviewer: string; reviewer_id: string | null; created_at: string; lines: { item: string; qty: number; note: string }[] } | null
}

export type PlanLine = { item: string; location: string; book_qty: number; unit_cost: number }
export type Plan = { locations: string[]; lines: PlanLine[] }

export type Row = {
  location: string
  item: string
  book_qty: number
  counted_qty: number | null
  variance_qty: number | null
  unit_cost: number | null
  variance_value: number | null
  status: 'match' | 'variance' | 'pending_review' | 'not_counted'
  count_source: string
  reviewer: string
  flag: string
  note: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, init)
  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep the status text */
    }
    throw new Error(plain(message))
  }
  return res.json() as Promise<T>
}

export const previewUrl = (clipId: string) => `${API}/clips/${clipId}/preview`

export const getPlan = () => request<Plan>('/plan')
export const getClips = () => request<Clip[]>('/clips')
export const getReconciliation = () => request<Row[]>('/reconciliation')

export function putPlan(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<{ lines: number; locations: number }>('/plan', { method: 'PUT', body: form })
}

export function uploadClip(file: File, sha256: string | null, who: { name: string; employeeId: string }) {
  const form = new FormData()
  form.append('file', file)
  if (sha256) form.append('client_sha256', sha256)
  form.append('captured_by', who.name.trim())
  form.append('captured_by_id', who.employeeId.trim())
  return request<Clip>('/clips', { method: 'POST', body: form })
}

export function postReview(clipId: string, body: { reviewer: string; reviewer_id: string; location?: string; lines: { item: string; qty: number; note: string }[] }) {
  return request<Clip>(`/clips/${clipId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** SHA-256 of the file as the device holds it, so the server can tell if the upload changed in transit. */
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export type InvObject = {
  id: number
  source: 'auto' | 'click' | 'drawn'
  box: [number, number, number, number]
  conf: number
  adjusted?: boolean
  included: boolean
  item: string | null
  click: [number, number] | null
}

export type Investigation = {
  id: string
  clip_id: string
  reviewer: string
  reviewer_id: string | null
  location: string | null
  status: 'open' | 'resolved'
  outcome: '' | 'confirmed' | 'unresolved'
  note: string
  frame_w: number
  frame_h: number
  machine_count: number | null
  objects: InvObject[]
  capped: boolean
  counts: { per_item: Record<string, number>; unassigned: number }
  events: { at: string; actor: string; action: string; detail: Record<string, unknown> }[]
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getInvestigations = (clipId: string) => request<Investigation[]>(`/clips/${clipId}/investigations`)
export const startInvestigation = (clipId: string, reviewer: string, reviewerId: string, location?: string) =>
  request<Investigation>(`/clips/${clipId}/investigations`, json('POST', { reviewer, reviewer_id: reviewerId, location }))
export const addClick = (id: string, x: number, y: number) => request<Investigation>(`/investigations/${id}/clicks`, json('POST', { x, y }))
export type Corner = { x: number; y: number }
export const drawBox = (id: string, box: [number, number, number, number], corners: Corner[], objectId?: number) =>
  request<Investigation>(`/investigations/${id}/boxes`, json('POST', { box, corners: corners.map((c) => [c.x, c.y]), object_id: objectId }))
export const deleteObject = (id: string, objId: number) => request<Investigation>(`/investigations/${id}/objects/${objId}`, { method: 'DELETE' })
export const patchObject =(id: string, objId: number, body: { included?: boolean; item?: string }) =>
  request<Investigation>(`/investigations/${id}/objects/${objId}`, json('PATCH', body))
export const resolveInvestigation = (id: string, outcome: 'confirmed' | 'unresolved', note: string) =>
  request<Investigation>(`/investigations/${id}/resolve`, json('POST', { outcome, note }))

/** Start on a frame the reviewer paused the video on: the page sends that exact frame as a picture. */
export function startFromFrame(clipId: string, image: Blob, atMs: number, who: { name: string; employeeId: string }, location?: string) {
  const form = new FormData()
  form.append('file', image, 'frame.png')
  form.append('at_ms', String(atMs))
  form.append('reviewer', who.name.trim())
  form.append('reviewer_id', who.employeeId.trim())
  if (location) form.append('location', location)
  return request<Investigation>(`/clips/${clipId}/investigations/from-frame`, { method: 'POST', body: form })
}
