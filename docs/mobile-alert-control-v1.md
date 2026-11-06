# Mobile alert control extension 1.1 (M38 / M106)

Approved scope: 2026-10-20, user request to close backend-first disposition and
automatic original upload. This is additive to the unchanged M37/M105 v1.0
contract; it does not introduce smart verification or deploy a running service.

## Authority and capture routing

The server is authoritative for human disposition. L1 still creates OPEN without
requiring a mobile confirmation. A new mobile L1 includes `X-Mobile-Producer-ID`,
the event's durable fact-operation UUID. The server derives the capture account
from the session and stores this immutable pair with the event. The UUID identifies
the original locally persisted capture, not a hardware identity or an additional
authorization credential. It is not returned in public alert feeds. The original
account, a current project capability and this capture ID are all required to
receive/complete an original request. Other installations without that local queue
record do not claim it. A fact replay cannot change the producer.

Historical events without a producer are not silently claimed from eventId,
membership, or a current login. Backend disposition remains available, but original
requests report `producer_unregistered`. New uploads after the upgrade are bound on
their first L1. Restoring an entire local queue is the same capture; replay remains
idempotent, not a new source.

## Disposition revision and concurrency

Public events carry nonnegative `dispositionRevision` (legacy history count is the
baseline). Each new committed human action increments it. Backend actions and the
mobile L2 carry `expectedRevision`. For producer-bound events it is mandatory.
Mismatch returns 409 `disposition_revision_conflict`, without an action or image
request. FALSE_POSITIVE cannot regress. Exact successful L2 operation replay is
resolved before CAS, so a lost response never turns a success into a conflict.

Mobile stores its action's base revision separately from the latest server
revision. Applying a server state is not a new human action. If an unsent action's
base has become stale, preserve its desired action in a conflict record, show the
server disposition, stop automatic submission and make the conflict visible.
Do not relabel an unexecuted mobile operation as successfully synced.

## Original request policy and API

ACKNOWLEDGED does not request an original. A backend FALSE_POSITIVE atomically
creates a pending original request when a registered mobile capture lacks an
uploaded original. An already uploaded original satisfies the request immediately.
Unregistered captures expose UNAVAILABLE/producer_unregistered, not a fake pending
request that no device can receive. Server-stream alerts do not ask a phone.

POST `/aiyoloapi/projects/{projectId}/alerts/{eventId}/original-requests`
requires alert-dispose capability. JSON: `{operationId, expectedRevision}`;
Idempotency-Key equals operationId (UUID). Same ID/body replays; reuse with another
body conflicts. A pending request is coalesced per event. The response is the
public event, including the latest `originalRequest` summary. A new explicit
operation may retry a prior UNAVAILABLE request. A normal detail GET is never an
implicit request to upload a file.

POST `/aiyoloapi/projects/{projectId}/alerts/mobile-sync`
requires current project alert-read/ingest rights and an operator session. JSON:
`{events:[{eventId,producerId}]}`, maximum 100. It returns `events` containing only
matching original captures, with canonical disposition, revision, and original
requests. Reads are non-consuming (no destructive claim). This makes response
loss, parallel scans and process restarts safe. It is not a cross-project global
queue. A nonmatching capture is omitted; no original producer identity is exposed.

POST `/aiyoloapi/projects/{projectId}/alerts/{eventId}/original-requests/{requestId}/receipt`
requires the original account and project ingest capability. JSON:
`{producerId,status,contentVersion?,sha256?,reason?}`. Status is UPLOADED or
UNAVAILABLE. UPLOADED is accepted only if the canonical original evidence/version
and digest really exist (uploaded by the existing multipart API). UNAVAILABLE uses
`no_local_capture`, `local_file_missing`, `local_media_purged`, or
`invalid_local_evidence`. Identical receipt replay succeeds; conflicting terminal
receipts return 409. Revocation pauses work, never invents an unavailable receipt.

Request states: PENDING -> UPLOADED | UNAVAILABLE. Request creation, backend
disposition, revision change and any request audit share the event transaction.
The server persists requests inside the locked durable event payload; it does
not depend on an in-memory notification or a new database table. Public feeds
return only the latest request summary, not the capture ID or receipt history.

## Mobile execution and retention

The worker drains L1, reconciles canonical disposition and requests, drains L2,
then uploads L3/L4 and submits receipts. It also periodically rescans the last
authorized project, with network constraints and bounded batches; UI/event-page
refresh enqueues an immediate best-effort scan. No mobile button is required.
WorkManager has no exact wake-up-time guarantee and cannot override force-stop.

Persist received requests and receipts in Room before acting. Received pending
requests protect local files, including during a failed receipt submission. A
server disposition can release the old OPEN protection only after it has really
been applied to Room; pending uploads/requests and existing verification protection
remain. The 7-day completed policy and 30-day user-confirmed recovery policy are
unchanged. Explicit purge marks corresponding requests unavailable. A request
arriving after lawful local deletion reports unavailable; no promise to restore
deleted files or discover requests while the device is offline.

## Joint acceptance vectors

1. L1 OPEN + thumbnail, no phone action; backend ACK revision 0 -> 1; no L4.
2. Backend FALSE_POSITIVE revision 0 -> 1; phone receives state/request, uploads
   original and receipt without a user click; exactly one action/request/object.
3. Explicit request on OPEN does not change disposition; repeat/coalesce safely.
4. Missing file reports UNAVAILABLE; backend state remains successfully disposed.
5. Lost receipt response, offline/new process, duplicate fetch and restart retain
   identities and finish without duplicate actions or overwriting evidence.
6. Other project/account/capture and revoked membership cannot receive/write;
   fresh reauthorization can resume the same original work.
7. Competing revision-0 actions: one commits; one 409; stale local action is kept
   as a visible conflict, not sent using a fabricated fresh revision.
8. Received pending request blocks automatic local purge; explicit 30-day purge
   yields unavailable, and shared-reference/read-upload lease protections remain.

Evidence must distinguish unit faults from real PostgreSQL/MinIO/API27 execution.
No production deployment, business-table reset or smart-review provider is needed.
