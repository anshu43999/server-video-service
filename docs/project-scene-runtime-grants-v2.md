# Scene runtime grant v2 — M39-T01

This versioned contract authorizes a client to use an approved scene plan. It is
not an offline license, artifact download credential, inference scheduler, or
proof that the client actually ran every model. The bearer grant lasts two
minutes; clients stop use at its expiry unless renewal succeeds.

## Endpoint and request

`POST /aiyoloapi/projects/{projectId}/scenes/{sceneId}/plans/{planId}/runtime-grants`
requires the authenticated `project.inspection.use` capability. Body fields are
the plan resolve identity (`planId`, `expectedRevision`, `target`, `inputType`,
`clientContractVersion`, `supportedExecutionModes`) plus `operation` and (except
for `start`) `grantToken`. `Idempotency-Key` is optional on `start`; if present,
reuse in the same account/project/scene/plan is rejected with 409 and never
returns or creates another credential. `X-Request-ID` is correlation/audit only;
it is not an idempotency key. Successful start/renew/heartbeat responses contain
`runtimeGrantContractVersion: 2`.

Single-member plans preserve v2 plan-resolve compatibility. Multi-member plans
require resolve contract v3 and an advertised capability matching the configured
`sync` or `async` mode. The grant atomically binds one complete ordered list:
member ID and `projectModelId`; exact model ID/version; target; each target artifact ID, SHA-256 and
size; primary artifact; approved parameter revision and digest. Parameter digest
is SHA-256 over UTF-8 canonical JSON: Unicode keys sorted by code point, arrays
kept in order, non-ASCII emitted as UTF-8, finite decimal numbers rendered
without exponent/trailing fractional zero, negative zero rendered as `0`, and
null/booleans in JSON spelling. Invalid surrogate strings and non-finite numbers
are rejected. A shared vector is in `project-scene-runtime-grants-v2-golden.json`.

The grant also binds account, project, scene revision, plan,
input, target, negotiated client contract/capabilities, execution mode, account
revision/platform role, project revision, and membership revision/creation
identity. Any changed authority generation or member snapshot rejects renewal;
the presented token is consumed on failed revalidation, so restoring permissions
cannot revive it. An HTTP authorization dependency may reject a revoked principal
before the handler is reached; that request cannot consume the old grant, but a
later renewal after restoration still fails the bound authority generation.

Tokens are random opaque values; only a SHA-256 digest and exact scope snapshot are
stored. Rotation (`heartbeat`/`renew`) atomically consumes the old token and
issues a new one with its minimal audit event. Replaying the consumed token is
denied. Stop is safe to repeat, including after scene revision changes or lease
expiry, and writes no model scheduling work. Cross-account/project/scene/plan,
input/target/revision mismatch is denied without consuming the legitimate token.
Idempotency covers duplicate starts only; rotation is intentionally one-use, not
response-replayable. Clients must persist the latest token before issuing another
heartbeat and must stop on denial or expiry.

An issued lease is valid only until its two-minute expiry: revocation is checked
on each renewal, not pushed to an offline client. PostgreSQL project/account
changes serialize with grant issuance. The file-backed model registry shares a
process lock with issuance; separate server processes do not share that lock.
Each renewal rechecks current model state, but a concurrent cross-process model
publication/revocation is not an atomic database transaction with grant issuance.
Deployments requiring immediate distributed revocation need a shared catalog
transaction or a separate revocation channel; this contract does not promise it.
Duplicate-start protection and repeat-stop history are retained for one day
after expiry/revocation (cleanup is bounded); callers must not reuse an old
idempotency key beyond that window.

The golden JSON also contains a multi-member API request and an executable
response projection. Tokens, timestamps and generated account/project IDs are
excluded; member order and exact version/target identity are checked by API tests.

## Migration and upgrade

The target test schema stores the complete project/scene/plan and project-model
membership snapshot as the authoritative grant scope. Legacy scenario-based
project assignments and compatibility projections are not imported. Test runs
use isolated databases and fresh fixtures; this contract does not authorize
resetting a running database or Default Project. Runtime grant rows are not
project-model assignments and must continue to bind the complete ordered member
set, exact target artifacts, approved parameters, and current authority revisions.

Android M108-T04/T05 can consume this contract without requiring server-side
inference. The server proves entitlement only; Android owns scheduling, result
aggregation, frame/result identity, and retirement of stale output. No Android
product implementation is included in M39-T01.
