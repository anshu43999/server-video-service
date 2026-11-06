# Project-scoped alerts and evidence

> Review endpoints and project-scoped review settings below are historical compatibility records only. M25-T09 retires review triggers and configuration writes (`410 verification_retired`); existing review data remains project-isolated and is not deleted.

M33-T06 makes project identity part of the complete alert lifecycle. An alert
event is identified by `(project_id, event_id)`; a bare `event_id` is not a
globally unique resource identifier.

## API contract

Supported alert resources are rooted at:

```text
/aiyoloapi/projects/{project_id}/alerts
/aiyoloapi/projects/{project_id}/alerts/{event_id}
/aiyoloapi/projects/{project_id}/alerts/{event_id}/evidence
# Historical read-only review result endpoint; no new client should call it.
/aiyoloapi/projects/{project_id}/alerts/{event_id}/verification
/aiyoloapi/projects/{project_id}/alerts/{event_id}/acknowledge
/aiyoloapi/projects/{project_id}/alerts/{event_id}/false-positive
/aiyoloapi/projects/{project_id}/alerts/{event_id}/close
/aiyoloapi/projects/{project_id}/alerts/mobile-ingest
/aiyoloapi/projects/{project_id}/alerts/false-positives/export
/aiyoloapi/projects/{project_id}/alerts/delivery/status
/aiyoloapi/projects/{project_id}/alerts/test-delivery
# Retired configuration endpoint (410).
/aiyoloapi/projects/{project_id}/verification/config
```

Management and app notification WebSockets use the same project root. Legacy
`/aiyoloapi/alerts` and `/aiyoloapi/verification` routes are hidden migration
aliases and require an explicit `X-Project-Id`. They never infer a default,
first, or only accessible project.

## Authorization and identity

- `PROJECT_OWNER` can read and dispose alerts, export false-positive data, and
  maintain delivery settings in that project.
- `PROJECT_USER` can read evidence, acknowledge an event, mark a false positive,
  and close an event. It cannot
  export training data or change project settings.
- A principal without active project membership receives `404`, including for
  WebSocket handshakes, so guessed event IDs do not reveal existence.
- Disposition and verification actors always come from the authenticated
  account ID. `X-Actor`, `X-Operator-Id`, and actor fields in mobile payloads
  are not trusted as identity.
- Platform administrators still enter an explicit project through the shared
  project authorization boundary and that entry remains auditable.

## Persistence boundaries

Alert events, disposition actions, false-positive feedback, historical verification
results/configuration, and delivery receipts
store `project_id`. Database lookups and uniqueness constraints use composite
project/resource keys. The process-memory fallback uses the same key shape.
Consequently, two projects can reuse an event ID without sharing disposition,
feedback, historical review state, receipts, lists, details, or exports.

Delivery subscribers and pending-task counters are partitioned by project.
Every dispatched event is stamped with the authenticated project and a
conflicting caller-supplied project is rejected. Notification WebSockets only
receive events from their authenticated project.

## Evidence isolation

MinIO objects use this partitioned layout:

```text
{prefix}/projects/{sha256(project_id)}/{event_hash_prefix}/{event_hash}.{ext}
```

Reads verify the configured bucket, the exact project hash prefix, and the
server-generated hash key shape before fetching an object. Local server alert
evidence uses the same project hash partition and accepts only generated
`evt-server-<24 lowercase hex>` event IDs. These constraints prevent project
ID disclosure in object keys, cross-project reference reuse, and traversal-
shaped evidence references.

The explicit `tools/migrate_alert_evidence_to_minio.py` operation also uses
composite project/event pagination, passes the persisted project to the object
store, and updates only that project's feedback. Duplicate event IDs across
projects remain safe with a batch size of one, interrupted limited runs, and
idempotent reruns. Payload project identity is normalized from the database
row rather than trusted from legacy JSON.

Inline data URLs remain a development compatibility path. Production evidence
storage remains fail-closed when the configured object store cannot persist an
upload. Device/service credentials and their project assignments are handled
by M33-T09; the current mobile ingest endpoint requires an authenticated human
project capability.
