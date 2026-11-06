# Project scene suite and run-plan contract v2

- Contract: `project-scene-suite-v2`
- Owner task: `M36-T12`
- Consumer task: Android `M107-T01`
- Status: run-plan/runtime-grant semantics remain in force; project-model membership is superseded by M33-T36.

## Purpose and boundary

Display metadata (M33-T52): project assignments and scene catalog members expose
`modelName` from the exact model asset's uploaded `name`. It is read-only display
metadata, not a stored scene edit, approval parameter, identity or authorization
input. Names may be duplicated or changed without reapproving a scene; all actions
still bind `modelId`, version, project and target. Missing names display
`未命名模型`, never a guessed name from another release or a technical ID as title.
User interfaces retain version/target and explicitly labelled technical details.

The project scene is a user-facing **business suite**. It groups model capabilities so
that a user can choose a job such as “site safety” without searching for every model.
It is not an instruction to execute every member. A suite, a model member, a run plan,
installation preparation, and runtime authorization are separate objects:

```text
suite (sceneId, revision)
  ├─ members (stable memberId -> exact model version and target)
  ├─ plans (explicit member selection + input + execution declaration)
  └─ installation projection (what is prepared locally; not a grant)
```

The current suite API is project-scoped and does not synthesize scenes from model
assignments. API contract versions describe client capabilities, not compatibility
with legacy scenario-based project assignments. A client that does not understand
the advertised suite/plan contract must fail closed and must not infer a plan from
the member list.

This contract covers image input and **local CameraX continuous frames** only. `video`
does not mean RTSP, WHEP, HLS, a remote camera, or a server-side video inference
session. No field in this contract authorizes remote video or server scheduling.

## Objects

### Suite

The suite is identified by `(projectId, sceneId, revision)`. `inputTypes` is the
derived union of enabled plan inputs and is display/filter metadata; it is not a
requirement that every member support every input. `available` means the suite is
visible and its project/model lifecycle checks passed. It is not a runtime grant.

```json
{
  "suiteContractVersion": 2,
  "projectId": "project-a",
  "sceneId": "site-safety",
  "name": "工地穿戴安全",
  "revision": 4,
  "inputTypes": ["image", "video"],
  "enabled": true,
  "approved": true,
  "available": true,
  "executionSupported": false,
  "members": [],
  "plans": [],
  "installation": {}
}
```

`members` is the canonical member list. Each member references one `projectModelId`
from the same project's enabled model inventory. New consumers must use the stable
`memberId`; `position` is display order only and is not identity.

### Member

Each member points to one project model inventory item and therefore one immutable
`(modelId, version, target)` and one exact target artifact projection. `inputTypes` is the allowed input subset for this suite member;
it cannot add a capability absent from the model release. A picture-only and a
CameraX-only member may coexist in one suite. The same model version may be referenced
by multiple members or plans, but each reference keeps its own plan parameters and
authorization identity.

```json
{
  "memberId": "member-helmet-image",
  "projectModelId": "pm-helmet-mobile",
  "modelId": "helmet",
  "version": "1.0.0",
  "target": "mobile",
  "position": 0,
  "inputTypes": ["image"],
  "execution": "single",
  "available": true,
  "targetReadiness": {"mobile": true}
}
```

`execution` on a member is a v1 compatibility declaration. A v2 client executes only
through a selected plan. `sync` and `async` remain configuration-only until a later
runtime task explicitly advertises support.

The frozen `parameterSnapshot` copied from a project inventory item at approval
must retain the model-parameter contract: `schemaVersion: 2`, `source`
(`default`, `custom`, or `inherited`), `updatedAt`, the exact project/model/version/
platform/revision identity, `inheritedRevision`, `detection`, and `alertRules`.
`audit` and `updatedBy` are not part of this consumer projection. Later profile
edits must not reconstruct or silently change an already approved snapshot.
Missing metadata in an existing test snapshot is not repaired on read: explicitly
save the project model again and review a new scene revision. This does not approve
the scene, start inference, or migrate legacy scenario assignments automatically.

Approval rejects an incomplete or invalid inventory snapshot with HTTP 409
`project_model_snapshot_invalid`, including `memberId`, `projectModelId`,
`modelId`, `modelVersion`, `target`, and `invalidFields`, plus a Chinese recovery
message. Metadata checks require integer `schemaVersion: 2`, a known `source`,
an explicit nullable/non-blank-string `updatedAt`, and a non-negative integer
`inheritedRevision` only for inherited parameters. Identity and parameter revision
must match the member. One invalid member rejects the entire approval without
changing its revision, previous approved snapshots, or approval audit. Drafts may
still reference an old assignment; approval never infers or repairs its metadata.

### Run plan

A plan is the only object that selects members for one operation. `memberIds` must be
unique, refer to members in the same suite revision, and each selected member must
support every plan input. The plan's `execution` describes result delivery semantics,
not a promise of physical parallel threads:

- `single`: one selected member and one terminal result;
- `sync`: wait for all required member terminal states before the aggregate is final;
- `async`: publish member results as they arrive and publish a final plan state.

The v2 freeze does not implement `sync` or `async`. An old or incapable client must
receive `409 execution_mode_not_supported`, not run the first member, serially fake
parallelism, or silently discard members.

```json
{
  "planId": "image-safety",
  "name": "静态安全检查",
  "inputTypes": ["image"],
  "memberIds": ["member-helmet-image", "member-ppe-image"],
  "execution": "sync",
  "enabled": true,
  "executionSupported": false
}
```

### Installation projection and local retention

Installation is preparation, not authorization. The server may expose a read-only
projection for the client; local storage owns the actual bytes and verification state.
The projection uses these statuses:

`not_installed`, `preparing`, `partial`, `ready`, `stale`, `failed`, `blocked`.

`ready` means every required member for the selected plan has a verified exact target
artifact. It does not mean that the user may run it offline. A suite can be `partial`
while one of its single-member plans is `ready`.

Local model bytes are deduplicated only by the complete trusted key:

```text
(serviceOrigin, target, modelId, version, artifactId, sha256)
```

The client maintains many retention references to one verified byte set. A reference
is either a user standalone retention or a suite member at a specific project,
`sceneId`, revision and `memberId`. A single `source` field is forbidden because one
model can be standalone-retained and referenced by multiple suites. Removing a suite
removes only its reference; physical deletion is allowed only when no standalone or
suite reference, active/candidate/previous slot, running lease, or rollback guard
remains. Unknown legacy provenance is conservatively retained and shown as unknown;
it is never rewritten as a user-selected standalone install.

Installation preparation, download and activation are separate operations. A failed
or cancelled preparation must not alter the active model or another suite's reference.
Suite upgrade prepares a new `(sceneId, revision)` set and atomically switches its
reference only after all required artifacts pass size, hash, signature and manifest
checks. Physical rollback alone never restores a revoked runtime grant.

## API shape reserved by this freeze

The following project-scoped paths use explicit suite and plan identity. No path
creates a scene by projecting project-model assignments:

```text
GET  /aiyoloapi/projects/{projectId}/scenes?contract=v2
GET  /aiyoloapi/projects/{projectId}/scenes/{sceneId}?contract=v2
GET  /aiyoloapi/projects/{projectId}/scenes/{sceneId}/plans/{planId}
GET  /aiyoloapi/projects/{projectId}/scenes/{sceneId}/installation
POST /aiyoloapi/projects/{projectId}/scenes/{sceneId}/installation/prepare
POST /aiyoloapi/projects/{projectId}/scenes/{sceneId}/plans/{planId}/resolve
```

M36-T14 implements the two installation paths. `GET .../installation` accepts a
required `target` and optional `planId` or repeated `memberId` query values; when
neither is supplied it projects all members for that target. `POST
.../installation/prepare` accepts `{expectedRevision, target, planId?, memberIds?}`
and records an account-scoped preparation projection keyed by the exact scene
revision. Preparation rechecks publication, target readiness, signature and bytes,
but never starts inference and always returns `runtimeAuthorization: false` and a
null `runtimeGrant`. The persisted record is not used as an offline execution
license and is invalidated by a later scene revision or permission/lifecycle check.

The implemented single-member plan response additionally carries `memberId`, exact
`modelId`/`modelVersion`, primary `artifactId`/`artifactSha256`, the full verified
target artifact list, and `parameterRevision`. Download and parameter URLs repeat
the current approval, project membership, scene revision, publication, target and
integrity checks. Multi-member plans remain configuration-only: v2 resolve returns
`execution_mode_not_supported`; explicit v3 capability negotiation below may return
a complete configuration snapshot, without starting execution.

Single-member resolution remains compatible with client contract v2. Multi-member
plan resolution uses resolve contract v3 and requires the request to include
`clientContractVersion: 3` plus `supportedExecutionModes` containing the exact
configured `sync` or `async` mode. This is client capability negotiation only;
it grants no account/project capability and does not make the service run inference.
The response binds project, scene revision, plan, execution declaration, every
member identity, exact version, target artifacts and that member's reviewed
parameter snapshot/revision. It carries `resolveContractVersion: 3`,
`resolutionOnly: true`, and `runtimeAuthorization: false`. Clients using v1/v2,
omitting the matching mode, or declaring a different mode fail closed with
`409 execution_mode_not_supported`. Single-member v2 clients retain the existing
response semantics. This endpoint is an online preflight, never a bearer token or
offline license. Every member, artifact and parameter endpoint rechecks current
membership, approval, publication, target, revision and integrity.

Approval persists a parameter source for each `(planId, memberId)` pair. Resolution
selects those exact approved snapshots and validates each snapshot against the
project/model/version/platform identity before returning any member. It never takes
client-supplied parameter values, drops a member, or starts synchronous/asynchronous
execution; actual multi-model runtime remains a later client/runtime capability.

### Multi-model run/result semantics reserved for Android M108

The v3 resolve snapshot is the immutable input to a future client run; it is not a
run request. A client-generated `runId` identifies one image or one sampled local
camera frame. Image identity uses a content digest scoped to the run (the image bytes
are not uploaded by resolve); a camera frame uses monotonically increasing
`frameSequence` and capture timestamp. Each result is namespaced by `memberId`,
`modelId`, exact version, parameter revision, and the same run/frame identity. Raw
labels and coordinates remain member-scoped; cross-model alert merging requires an
explicit rule and must not happen by label coincidence.

For `sync`, the client submits the same input identity to every resolved member and
returns one terminal batch summary after all members are terminal or the batch
deadline expires. The summary distinguishes `complete`, `partial`, `failed`,
`timed_out`, and `cancelled`; a failed or timed-out member is never rewritten as a
successful empty detection. For `async`, each member may publish an incremental
terminal result independently, followed by one terminal batch summary. Every
increment carries `runId`, member identity, frame sequence/timestamp (for camera),
parameter revision and result timestamp/age. Duplicate, out-of-order, stale-frame
and post-cancel results are ignored/retired, not overlaid as current results.

Timeout, cancellation and partial success are client/runtime outcomes, not grants
from the service. Resolve remains online and every result/alert must be retired if
project generation, scene revision, member release, approval or authorization changes.
This vocabulary freezes the interoperability contract only; it does not claim that
the Android scheduler, multi-model inference, alert aggregation, or a service-side
execution API exists.

### Online runtime lease (M39-T01)

```text
POST /aiyoloapi/projects/{projectId}/scenes/{sceneId}/plans/{planId}/runtime-grants
```

The request uses the same exact revision, target, input and client contract fields
as plan resolve, plus `operation` (`start`, `renew`, `heartbeat`, or `stop`) and,
except for `start`, the current `grantToken`. An approved, enabled single-member or
multi-member plan can receive a runtime lease. Single-member plans retain client
contract v2 compatibility; multi-member plans require contract v3 and the configured
`sync`/`async` capability. The response token is opaque and short-lived
(two minutes); only its digest is persisted, so multiple workers share the same
revocation state without storing a usable bearer credential. `renew` and `heartbeat`
consume the old token and rotate it.
Every start/renew/heartbeat reruns plan resolution, including live membership,
approval, publication, target artifact integrity and parameter snapshot checks; the
lease scope records account, project, scene revision, plan execution mode, input,
target, and the complete ordered member set. Each member entry binds stable member
identity, exact model/version, primary artifact identity and SHA-256, parameter
revision, and a SHA-256 of the approved parameter snapshot. Each member entry also
binds its `projectModelId`; the complete ordered composite snapshot is authoritative
for renewal. A member disappearing, being reordered, changing identity,
version, artifact or parameters, or failing any current authorization check rejects
renewal as a whole; no partial grant is issued. Any mismatch fails closed.
`stop` revokes the current lease and does not require the old scene revision to remain
valid. Audits never store the bearer token. Installation preparation and both resolve
contracts remain `runtimeAuthorization: false`; client capability declarations do
not mint a lease. The versioned lease contract and golden vectors are specified in
[project-scene-runtime-grants-v2.md](project-scene-runtime-grants-v2.md).

The lease is an online runtime gate, not an offline license or a server-side inference
session. A client must stop relying on it when heartbeat/renewal is denied and must
not continue beyond `expiresAt` without a successful renewal.

### Editable member profile and explicit reapproval (M36-T18)

```text
GET /aiyoloapi/projects/{projectId}/scenes/{sceneId}/members/{memberId}/parameter-profile?sceneRevision=N
PUT /aiyoloapi/projects/{projectId}/scenes/{sceneId}/members/{memberId}/parameter-profile?sceneRevision=N
```

These administration endpoints expose the editable scene member profile, not the frozen
execution parameter URL. GET requires `project.scenes.manage`; PUT additionally
requires `project.models.assign`. The server derives exact model/version/platform
from the member's current project model inventory item, requires a current scene
revision, and rejects injected identities.
PUT accepts the existing parameter schema (`schemaVersion`, `detection`,
`alertRules`, `expectedRevision`) with profile-level CAS. The writer rechecks current
account/project authority, scene revision/member and release readiness inside the
project transaction lock; the member must resolve to an enabled project model inventory item.

M29-T22: the editable profile is isolated by project/scene/member and exact model,
version and platform. PUT returns `sceneRevision` (incremented), invalidates approval
and old grants/URLs immediately, and stores the draft in the existing member JSON
snapshot; no database migration or model download is needed. GET initially uses the
member's frozen profile or assigned project-model snapshot. Reapproval freezes the
draft into each participating plan's `parameterSources`. Other scenes and standalone
inventory parameters remain unchanged. Explicit inventory revision synchronization
discards an override based on the older inventory revision. `alertRules[].enabled`
is the sole recognition-and-alert switch; disabled best-class candidates are rejected
in postprocessing before NMS/result limits, never relabeled. Empty means no detections.
Full class IDs/labels remain unchanged. Alert thresholds and cooldown still apply.
This does not grant an offline runtime license. Plan-specific overrides within a
single scene member are outside this editor's scope.

Stable errors include:

| HTTP | code | Meaning |
|---:|---|---|
| 400 | `project_context_required` | No explicit project scope |
| 403 | `project_capability_required` | Missing suite/inspection capability |
| 404 | `scene_not_found` / `plan_not_found` | Not visible in current project |
| 409 | `revision_conflict` | Suite revision is stale |
| 409 | `scene_input_not_supported` | Selected plan/member does not accept input |
| 409 | `execution_mode_not_supported` | Client/runtime cannot execute plan mode |
| 409 | `scene_installation_incomplete` | Required artifact is not ready |
| 409 | `model_target_not_ready` / `model_not_project_authorized` | Exact target/member is unavailable |
| 422 | `invalid_scene_suite` | Duplicate member/plan identity or malformed relation |

## Compatibility and security gates

All v1 project, account, capability, approval, revision, parameter, target and
signature gates remain in force. Suite membership does not grant a model assignment,
and a locally retained model does not grant suite execution. Account/project
generation, late-callback retirement, online revalidation, lifecycle shutdown and
remote-video retirement remain mandatory. Multi-member resolve requires contract
v3 and matching advertised execution capability; runtime authorization follows
the M39 v2 grant contract. Clients must advertise only modes they actually
implement. A client without multi-model execution keeps these plans display-only
and fails closed; server entitlement does not establish Android runtime support.

