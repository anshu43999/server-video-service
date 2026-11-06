export type AlertSeverityKey = 'critical' | 'important' | 'normal'
export type AlertDispositionStatus = 'OPEN' | 'ACKNOWLEDGED' | 'FALSE_POSITIVE' | 'CLOSED' | string
export interface AlertDispositionHistoryItem {
  status: AlertDispositionStatus
  actor?: string | null
  actedAtUs?: number | string | null
  note?: string
}

export interface AlertDisposition {
  status: AlertDispositionStatus
  actor?: string | null
  actedAtUs?: number | string | null
  note?: string
  history?: AlertDispositionHistoryItem[]
}

export type AdviceGenerationStatus = 'GENERATED' | 'NO_MATCH' | 'PARTIAL' | 'FAILED_RETRIEVAL' | 'FAILED_GENERATION'
export interface AdviceGeneration {
  contractVersion: '1.0'; generationId: string; projectId: string; eventId: string; requestedBy: string
  idempotencyKey: string; retryOfGenerationId?: string | null; status: AdviceGenerationStatus; reasonCode?: string | null
  matchKey: { alertTypeId: string; recognitionCategoryId: string } | null
  advice: { title: string; steps: Array<{ stepId: string; order: number; title: string; instruction: string }>; cautions: string[] } | null
  references: Array<{ referenceId: string; documentTitle: string; documentNumber?: string | null; documentVersion: string; chapter?: string | null; clauseId?: string | null; excerpt: string; sourceName: string; sourceType: string; effectiveDate?: string | null }>
  knowledgeEntryId?: string | null; knowledgeRevision?: number | null; knowledgeOrigin?: 'SYSTEM' | 'PROJECT' | 'PROJECT_OVERRIDE' | null; systemKnowledgeVersion?: number | null; matchExplanation?: string | null
  retrievalProvider: string; generationProvider: string; sourceNotice: string
  error?: { stage: 'RETRIEVING' | 'GENERATING'; code: string; retryable: boolean } | null
  createdAt: string; completedAt: string
}

export interface AlertProvenance {
  kind: 'SCENE' | 'STANDALONE'
  model: { modelId: string; name: string; version: string }
  scene?: { sceneId: string; name: string; revision: number }
  plan?: { planId: string; name: string }
  memberId?: string
}

export interface AlertEvent extends Record<string, unknown> {
  eventId: string
  dispositionRevision?: number
  originalRequest?: {
    requestId: string
    status: 'PENDING' | 'UPLOADED' | 'UNAVAILABLE'
    unavailableReason?: string
    contentVersion?: number
  }
  displayName?: string
  label?: string
  ruleId?: string
  ruleVersion?: number
  sourceId?: string
  subjectKey?: string
  origin?: string
  provenance?: AlertProvenance | null
  state?: string
  severity?: string
  notifySeverity?: string
  startedAtUs?: number | string | null
  confirmedAtUs?: number | string | null
  lastSeenAtUs?: number | string | null
  escalatedAtUs?: number | string | null
  evidence?: Record<string, unknown> & { original?: Record<string, unknown>; thumbnail?: Record<string, unknown> }
  effectiveThresholds?: Record<string, unknown>
  detectionResults?: unknown[] | Record<string, unknown>
  disposition?: AlertDisposition
  model?: { modelId?: string; name?: string; modelName?: string; version?: string } | null
}

export interface AlertsResponse { events: AlertEvent[] }
export type AlertsPhase = 'idle' | 'loading' | 'ready' | 'error'
export type DetailPhase = 'idle' | 'loading' | 'ready' | 'error'
export type DispositionAction = 'ACKNOWLEDGED' | 'FALSE_POSITIVE'
