import type { AlertEvent } from './types'

export interface EvidenceBox {
  label: string; confidence: number; left: number; top: number; right: number; bottom: number
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined
}

/** Accept only the immutable snapshot belonging to this evidence, never a latest detection list. */
export function evidenceBoxes(event: AlertEvent): EvidenceBox[] {
  const overlay = record(event.evidence?.displayOverlay)
  if (!overlay || overlay.version !== 1 || overlay.bakedIn !== false
    || typeof overlay.capturedAtUs !== 'number' || !Number.isFinite(overlay.capturedAtUs)
    || overlay.capturedAtUs < 0 || !Array.isArray(overlay.detections)) return []
  return overlay.detections.slice(0, 100).flatMap((value: unknown) => {
    const row = record(value)
    const box = record(row?.box)
    if (!row || !box || typeof row.label !== 'string' || !row.label.trim()
      || typeof row.confidence !== 'number' || !Number.isFinite(row.confidence)
      || row.confidence < 0 || row.confidence > 1) return []
    const left = box.left ?? box.x
    const top = box.top ?? box.y
    const right = box.right ?? (typeof left === 'number' && typeof box.w === 'number' ? left + box.w : undefined)
    const bottom = box.bottom ?? (typeof top === 'number' && typeof box.h === 'number' ? top + box.h : undefined)
    if (typeof left !== 'number' || typeof top !== 'number' || typeof right !== 'number' || typeof bottom !== 'number'
      || [left, top, right, bottom].some((n) => !Number.isFinite(n) || n < 0 || n > 1)
      || right <= left || bottom <= top) return []
    return [{ label: row.label.trim().slice(0, 160), confidence: row.confidence, left, top, right, bottom }]
  })
}

export function containImage(viewWidth: number, viewHeight: number, imageWidth: number, imageHeight: number) {
  if ([viewWidth, viewHeight, imageWidth, imageHeight].some((n) => !Number.isFinite(n) || n <= 0)) return undefined
  const scale = Math.min(viewWidth / imageWidth, viewHeight / imageHeight)
  const width = imageWidth * scale, height = imageHeight * scale
  return { x: (viewWidth - width) / 2, y: (viewHeight - height) / 2, width, height }
}
