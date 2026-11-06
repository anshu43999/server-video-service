# Mobile alert tiered-upload contract v1

Status: frozen v1.0.0; Android M105-T01 and server M37-T01 jointly approved the baseline on 2026-10-19.

This contract separates the durable alert fact, operator disposition, and evidence bytes. It preserves the existing project-scoped mobile-ingest route during migration and does not change model `candidate` / `active` / `previous` lifecycle semantics.

## Version and identity

- Contract version: `1.0.0`; clients send `X-Mobile-Alert-Contract: 1.0`.
- All routes are scoped under `/aiyoloapi/projects/{projectId}`. Project identity in the URL must match the authenticated project context. Use the current operator session; never accept a project ID or object key as authorization by itself.
- `eventId` is immutable within `(projectId, eventId)`. Mobile IDs retain the existing `local:` namespace. A fact replay with the same event ID and same immutable identity is idempotent. Reuse with a different source/rule/subject/started timestamp is `409 event_identity_conflict`.
- Operation keys are opaque UUIDs and stable across retries. The server scopes them by project, event, operation kind, and actor. Evidence identity is `(projectId, eventId, evidenceType, contentVersion, sha256)`; thumbnails and originals never overwrite each other.

## L1: alert fact

`POST /aiyoloapi/projects/{projectId}/alerts/mobile-ingest`
`Content-Type: application/json`

Required headers: authenticated operator session and `X-Mobile-Alert-Contract: 1.0`.

The JSON body is the current mobile alert fact envelope (`eventId`, `origin`, `ruleId`, `sourceId`, `subjectKey`, `label`, `state`, `severity`, `notifySeverity`, `startedAtUs`, `confirmedAtUs?`, `lastSeenAtUs`, `effectiveThresholds`, `detectionResults`). `disposition` is omitted; the server creates the fact with `OPEN`. `evidence` contains metadata/references only and MUST NOT contain image bytes, data URLs, base64, local filesystem paths, or caller-controlled object keys. Until evidence endpoints are available, an empty object is valid.

The server returns `202` with `{ "event": { ... }, "created": true|false }`. A replay returns the canonical event and does not reset a disposition or erase already registered evidence. Timestamp validation and existing event/project authorization remain in force.

## L2: disposition delta

`PUT /aiyoloapi/projects/{projectId}/alerts/{eventId}/disposition`
`Content-Type: application/json`

Required header: `Idempotency-Key`, which MUST equal `operationId` in the JSON body.

Body:

```json
{
  "operationId": "9f36e82b-0e8a-4b51-a3bd-32a5b1e344dd",
  "status": "ACKNOWLEDGED",
  "actedAtUs": 1790000000000000,
  "evidenceUnavailableReason": null
}
```

The actor is derived from the authenticated session and is never client supplied. Allowed statuses are `ACKNOWLEDGED` and `FALSE_POSITIVE`. `evidenceUnavailableReason` is an optional stable enum (`no_local_capture`, `local_file_missing`, `upload_not_permitted`, `capture_failed`), not free-form text. No evidence bytes are accepted here.

The client MUST wait for a successful L1 response before L2. If an L2 attempt races ahead or the fact is absent, the server returns retryable `409 event_not_ingested` and creates no orphan disposition. Repeating the same operation ID and payload returns the original result; reusing it with a different payload returns `409 idempotency_conflict`. A new deliberate user action requires a new operation ID. Disposition state must not regress from a terminal `FALSE_POSITIVE`; repeated identical action is idempotent.

## L3/L4: independently uploaded evidence

`POST /aiyoloapi/projects/{projectId}/alerts/{eventId}/evidence`
`Content-Type: multipart/form-data`

Required header: `Idempotency-Key`, a stable UUID for the upload attempt series. Parts: `evidenceType` (`thumbnail` or `original`), `contentVersion` (positive integer), `sha256` (64 lowercase hex characters), and `file` (image bytes). Thumbnail target max is 128 KiB; original target max is 5 MiB. These are decoded byte limits; deployment may lower them but cannot silently raise them without a contract revision. Accept only JPEG/PNG/WebP with matching file signature. Stream and enforce the configured limit before persistent storage.

The event fact must already exist, otherwise return `404 event_not_found`; a revoked or mismatched project capability is denied. A new identity returns `201`; same identity and same digest returns `200` with the canonical reference. Same `(project,event,type,version)` with a different digest returns `409 evidence_version_conflict`; use a new content version to intentionally replace. A storage failure returns a retryable server error and leaves no visible reference or orphaned permanent object.

Success response:

```json
{
  "eventId": "local:camera-a:123",
  "evidence": {
    "type": "thumbnail",
    "contentVersion": 1,
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "contentType": "image/jpeg",
    "byteLength": 48210,
    "uri": "/aiyoloapi/projects/project-a/alerts/local%3Acamera-a%3A123/evidence/thumbnail/1"
  }
}
```

Authenticated read: `GET /aiyoloapi/projects/{projectId}/alerts/{eventId}/evidence/{evidenceType}/{contentVersion}`. Require the project's alert-read capability. The current single-image `/alerts/{eventId}/evidence` URL remains a compatibility read alias for the canonical primary thumbnail while old clients are supported. It is not an upload API.

L3 thumbnail is uploaded according to the mobile fact policy. L4 original is conditional: user-requested review, false-positive feedback, or explicit project sample-return authorization. The server MUST NOT infer permission to upload L4 from the presence of a local file.

## Error and retry classification

Errors use `{ "detail": { "code": "...", "message": "...", "retryable": true|false } }`.

| HTTP | Codes/examples | Client action |
|---|---|---|
| 400/415/422 | `invalid_event`, `invalid_disposition`, `invalid_evidence`, `unsupported_media_type`, `digest_mismatch` | Permanent; surface/record, do not retry unchanged |
| 401/403 | `unauthenticated`, `project_access_denied`, `capability_required` | Pause queue; require re-auth/authorization; do not tight-loop |
| 404 | `event_not_found`, `evidence_not_found` | For L2/L3 dependency race, retry only after L1 success; otherwise permanent |
| 409 | `event_identity_conflict`, `idempotency_conflict`, `evidence_version_conflict` | Permanent conflict; do not retry unchanged |
| 413 | `evidence_too_large` | Permanent; recompress or require a new version |
| 408/429/5xx, network timeout | `temporarily_unavailable`, `rate_limited`, `storage_unavailable` | Retry with same operation identity, exponential backoff + jitter; honor `Retry-After` |

Unknown timeout outcome is resolved by replaying the same idempotency identity, never by minting a new operation ID for an automatic retry. Retry policy is bounded and observable on device; a user action may resume a paused queue.

## Retention and cleanup defaults (jointly approved)

- Server evidence retention: 90 days from upload; explicit, audited sample-retention marker may extend to 365 days. No implicit indefinite retention.
- Client evidence retention after all required uploads complete: 7 days. Pending/failed media is protected for at most 30 days from capture; at 7 days overdue show a recoverable warning and retry state, and at 30 days require explicit user action/export before local purge. Never delete a file while referenced by an active upload/read lease.
- Server cleanup first marks eligible rows, waits a 24-hour grace period, rechecks event/evidence references and active operations, then removes object and metadata idempotently. Dry-run, batch limit, audit trail, and retry/continuation are required.
- `FALSE_POSITIVE` is not an indefinite retention exemption; only an explicit retention marker with expiry extends retention.

The defaults above are the approved v1 baseline. Any change to these values requires a contract revision and coordinated Android/server review.

## Shared conformance and cost baseline (approved)

The golden sequence uses one project and event: L1 fact; replay L1; L2 disposition; replay L2; upload L3; replay L3; upload L4; attempt disposition-before-fact on a second event and verify no orphan; revoke project access and verify subsequent writes/read fail; restore access; exercise retryable timeout then replay with same keys; run expiry cleanup with a pending local item and an explicitly retained server object. Both repos use the same IDs, payload fixtures, timestamps, digests, and expected statuses.

Cost comparison uses one 8-hour camera-shift, 1,000 confirmed events, 300 KiB compressed primary image, 48 KiB thumbnail, 5 MiB maximum L4 original, 10% L4 trigger rate, 2% transient retry rate, 7-day local completed-media retention, 30-day maximum local pending protection, and 90-day server default retention. Report raw request bytes, stored object bytes-days, request count, and p50/p95 API latency separately. Actual production event/trigger/retention rates must replace these fixed comparison assumptions before rollout sizing.

## Compatibility and rollout

Existing `POST .../alerts/mobile-ingest` with optional disposition and inline `snapshotDataUrl` remains a temporary compatibility path for legacy clients. New v1 clients MUST use L1/L2/L3/L4 split routes and MUST NOT send inline base64. Deprecation/removal date is not set by this document; server rollout must keep legacy behavior until a separately approved compatibility window and usage telemetry permit removal.

## Freeze evidence

- Android M105-T01 approves routes, fields, limits, enums, retry semantics, retention and cost baseline in response to the user's confirmation on 2026-10-19.
- Service and Android golden fixtures are byte-for-byte aligned and include positive, duplicate, race, authorization, oversize and retry vectors.
- WorkManager decision and Room migration plan are recorded in `mobile-app/docs/mobile-alert-tiered-upload-v1-android.md`.
- Contract SHA-256 and repository references are captured in both Harness completion records.
