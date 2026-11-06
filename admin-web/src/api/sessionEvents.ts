export const SESSION_EVENT_KEY = 'aiyolo.session.changed'
/** Notification only: never store account, project, token or business payload. */
export function notifySessionChange() {
  try { localStorage.setItem(SESSION_EVENT_KEY, crypto.randomUUID()) } catch { /* Focus checks remain authoritative. */ }
}
