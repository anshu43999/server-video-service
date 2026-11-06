import { ApiError } from '../../api/errors'
/** Uncertain writes must be reconciled by a fresh read, never auto-replayed. */
export function requiresReload(error: unknown) {
  return error instanceof ApiError && (error.status === 409 || (error.status ?? 0) >= 500 || ['network','timeout','invalid-response'].includes(error.kind))
}
