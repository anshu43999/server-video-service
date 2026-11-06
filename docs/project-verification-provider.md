# Project Verification Provider Boundary

> **Retired 2026-10-28.** This document describes the historical M25 provider boundary only. M25-T09 disables provider initialization and all review/configuration writes; legacy review mutation endpoints return `410 verification_retired`. Existing result/configuration records are retained. AI alert handling advice remains a separate feature documented by `ai-alert-advice-api-v1.md`.

The verification API is project-scoped.  The authenticated project supplies the
alert and evidence; the mobile client never supplies a provider URL, credential,
or remote image URL.

The optional server adapter is enabled only when the deployment supplies:

- `VERIFICATION_PROVIDER_ENDPOINT`
- `VERIFICATION_PROVIDER_API_KEY`
- `VERIFICATION_PROVIDER_TIMEOUT_SECONDS` (1-120 seconds, default 60)

The provider receives an inline `data:image/...;base64` payload resolved by the
server from that project's evidence.  Paths, object keys, credentials and raw
provider responses are never persisted in the project result.  The adapter
accepts only `TRUE_POSITIVE`, `FALSE_POSITIVE`, and `UNCERTAIN`, mapping them to
`CONFIRMED`, `SUSPECTED_FALSE_POSITIVE`, and `INCONCLUSIVE`.  All transport,
authentication, quota and malformed-response failures are fail-open: the
original alert remains available. Definite failures are `FAILED`; unknown
transport/timeout or malformed response outcomes are `UNKNOWN`, never success.

`providerConfigured` in the project policy is derived from deployment
availability; the project settings request cannot claim a provider is present.
This keeps project policy and platform credentials separate while allowing the
same project-aware Android client to consume the result.

## Explicit retry extension (M37-T06, 2026-10-20)

The existing project verification POST accepts optional `operationId` and
`retryOfAttemptId` (canonical UUID strings). When supplied, `Idempotency-Key`
must equal `operationId`; a retry requires both fields. Legacy `{}` calls remain
deduplicated by project/event and never implicitly start another attempt.

An intentionally new retry is allowed only when the latest result is `FAILED`
and `retryable=true` for `RATE_LIMITED` or `PROVIDER_UNAVAILABLE`. The client sends
a new operation UUID with the latest failed `attemptId`. An event permits at most
3 actual dispatches, rechecking privacy, readable evidence, provider configuration
and daily quota every time. Disabled/unauthorized/missing-image/unconfigured/quota
refusals do not call a provider and have no new attempt ID or quota reservation.

Replaying the same operation and request body returns that operation's result,
even after a later successful retry. Changed payloads return `409 idempotency_conflict`;
stale predecessor IDs, concurrent distinct retries and nonretryable outcomes return
409 (`retry_conflict`, `retry_not_allowed`, or `retry_limit_exceeded`). Fetch GET
verification for the latest state rather than treating an old replay as current.

Before outbound I/O, a short transaction locks the project, reserves daily quota,
and commits a unique attempt ID, operation snapshot and `PENDING` state to the
existing JSON payload. No schema migration is required. Provider I/O does not
hold a database transaction, project lock or process store lock. A second short
transaction settles the result and attempt history. Actual dispatches consume
internal quota even on a definite provider failure; local deterministic refusals
do not. `callsToday` and dashboard `used` are not supplier billing estimates.

`NETWORK`, `TIMEOUT_UNKNOWN`, malformed responses and unexpected adapter failures
retain a reservation with `UNKNOWN`, `retryable=false` and
`recoveryAction=RECONCILE_PROVIDER_DO_NOT_REPLAY`. After process loss, a committed
pending attempt survives restart; after 180 seconds its unknown state is exposed
on replay and persisted on GET. A late original response can settle that same
attempt. Neither expiration nor restart initiates another supplier call.

Recovery: query the latest verification state and correlate the attempt ID with
supplier request logs. If the result cannot be established, retain UNKNOWN and
use human disposition; do not bypass the guard with a new operation ID or reset
quota. No automatic reconciliation/unlock endpoint is claimed. The wire adapter
sends attempt ID as `X-Request-ID` and `Idempotency-Key`, but provider support is
not assumed: `providerBilling=UNVERIFIED`, no external exactly-once billing guarantee.

Results contain only project-scoped image references, not inline images or keys.
Independent original/thumbnail evidence is resolved server-side under its read
lock. Annotation updates merge only verification fields and cannot overwrite
concurrent evidence uploads or human dispositions. The admin review button offers
explicit retries only for retryable results and locks unknown outcomes.

Current local deployment inspection: database configured; supplier endpoint/key
not configured. Unit tests use an explicit fixture adapter; PostgreSQL tests use
the real configured remote database with disposable schemas. This is not evidence
of live supplier acceptance. That environment gate remains part of M37-T07.
