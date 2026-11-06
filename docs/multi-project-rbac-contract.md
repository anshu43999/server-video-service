# Multi-project RBAC and data-isolation contract

> 2026-10-15 / M34-T04 视频范围修订：本文旧直播分发/移动远程播放条款由 [ADR-003](adr-003-analysis-alerts-only.md) 取代。保留PC同源预览、输入分析、项目隔离、正式告警和证据；回退须符合 [分发退役升级手册](media-retirement-upgrade.md)，不能恢复旧发布器/移动直播。本文其他账号、项目、迁移、恢复、安全与审计门禁仍有效；先本地真实验收，再部署。

- Contract version: 1.0
- Frozen date: 2026-10-10
- Owner task: M33-T01
- Mobile counterpart: `mobile-app/docs/mobile-project-context-contract.md` / M100-T01
- Status: frozen for implementation

## 1. Objective

The system changes from a single global business space with `admin` and `operator` accounts to a platform that contains multiple isolated projects. The contract covers identity, authorization, data ownership, model governance, realtime channels, migration, offline behavior, audit, operations, and end-to-end acceptance. UI visibility is never an authorization boundary.

The first release supports one account in multiple projects and different roles in each project. It does not simplify membership to one `projectId` or one project role stored directly on the account.

## 2. Terms and identities

### 2.1 Account

An account is a human identity with an immutable `accountId`, a unique login name, enabled state, and a platform role. Usernames are display/login attributes and are not foreign keys for new domain records.

Platform roles:

- `PLATFORM_ADMIN`: manages projects, accounts, global model assets, deployment and platform audit.
- `NORMAL_USER`: has no business data access without an active project membership.

### 2.2 Project

A project is the isolation and ownership boundary for business data. It has an immutable `projectId`, unique project code, display name, lifecycle state, revision, creator, and timestamps.

Lifecycle states:

- `ACTIVE`: normal reads and authorized writes.
- `SUSPENDED`: business writes and runtime starts are blocked; authorized maintenance and recovery remain available.
- `ARCHIVED`: immutable business history remains queryable to authorized administrators; runtime work, downloads, ingest and ordinary member access stop.

Hard deletion is not part of the first release. Retention-expiry deletion requires a separate destructive-data contract.

### 2.3 Project membership

`ProjectMembership` joins an account to a project. The pair `(projectId, accountId)` is unique. Membership has a role, enabled state, revision, creator and timestamps.

Project roles:

- `PROJECT_OWNER`: maintains members and project-owned configuration and data.
- `PROJECT_USER`: uses inspection, viewing, alert and disposition functions without project or model governance rights.

A project must always retain at least one enabled `PROJECT_OWNER`. Removing or disabling the last owner is rejected. Platform administrators do not become silent members of every project. They explicitly enter a project for support or management, and that access is audited.

### 2.4 Device and service principal

Human sessions are not reused as permanent device credentials. A project-bound device/service principal has an immutable ID, project ID, capability set, expiry, revocation state, credential digest, last-used time and audit history. Plain credentials are returned once and never stored or logged.

## 3. Capability model

Server endpoints authorize capabilities, not role-name string comparisons. Roles map to a frozen default capability set; future custom roles may be added without changing endpoint semantics.

Core capabilities:

| Capability | Platform admin | Project owner | Project user |
|---|---:|---:|---:|
| `platform.projects.manage` | yes | no | no |
| `platform.accounts.manage` | yes | no | no |
| `platform.models.manage` | yes | no | no |
| `platform.audit.read` | yes | no | no |
| `project.read` | audited entry | yes | yes |
| `project.members.manage` | audited entry | yes | no |
| `project.streams.manage` | audited entry | yes | no |
| `project.rules.manage` | audited entry | yes | no |
| `project.models.assign` | audited entry | yes | no |
| `project.scenes.manage` | audited entry | yes | no |
| `project.scenes.approve` | audited entry | yes | no |
| `project.settings.manage` | audited entry | yes | no |
| `project.inspection.use` | audited entry | yes | yes |
| `project.streams.view` | audited entry | yes | yes |
| `project.alerts.read` | audited entry | yes | yes |
| `project.alerts.dispose` | audited entry | yes | yes |
| `project.exports.create` | audited entry | yes | no |
| `project.audit.read` | audited entry | yes | no |

Project users may acknowledge alerts and mark false positives. These are operational use actions, not project configuration. The server derives the actor from the authenticated principal; legacy `X-Operator-Id` input cannot override it.

## 4. Model governance

Global model assets and project model assignments are separate domains.

Platform administrators exclusively govern:

- model families and immutable versions;
- uploads, conversion and calibration;
- signed artifacts and trusted keys;
- publish, deprecate and revoke lifecycle actions;
- global compatibility and release gates.

Project owners govern only project assignments:

- choose a `PUBLISHED` model version for an inspection scenario;
- choose or create an allowed project parameter revision;
- enable or disable the assignment;
- bind project streams and mobile scenarios to the assignment.

Project users may read the effective assignment and download its required signed artifact to use inspection features. Downloading a required artifact is resource consumption, not model maintenance. They cannot browse unauthorized assets, select another model, activate a version, roll back, uninstall protected assets, edit parameters, publish, deprecate or revoke.

The first release does not implement project-private uploaded models. A later contract may add `GLOBAL` and `PROJECT_PRIVATE` visibility without changing project assignment semantics.

## 5. Project-owned resources

The following records and runtime objects require a non-null `projectId` after migration:

- stream configurations, stream runtime sessions and media publication paths;
- rule definitions, bindings and rule audit entries;
- alert events, disposition actions, false-positive feedback and evidence;
- alert verification records, project verification settings and project quotas;
- alert delivery policies and receipts;
- project model assignments and project parameter overrides;
- business dashboard aggregates, exports and project audit entries;
- device/service principals and their usage audit;
- mobile-ingested events and idempotency keys.

Global model binaries, conversion infrastructure, calibration assets, platform health and platform configuration remain platform-scoped. A global row must never be returned through a project endpoint unless the project has an effective authorization or assignment for it.

Identifiers that can be reused between projects use composite uniqueness such as `(projectId, streamId)` or immutable globally unique internal IDs plus project-qualified external keys. Runtime dictionaries, locks, caches and queues must use project-qualified keys.

## 6. Explicit project context

Long-term project business APIs use explicit resource paths:

```text
/aiyoloapi/projects/{projectId}/streams
/aiyoloapi/projects/{projectId}/alerts
/aiyoloapi/projects/{projectId}/rules
/aiyoloapi/projects/{projectId}/model-assignments
```

WebSocket and media entry points are project-qualified as well. Compatibility endpoints may temporarily accept an `X-Project-Id` header only during the migration window. After multi-project activation, a missing project context is an error and never means "use the first project", "use the only active project", or "query all projects".

Every request resolves:

```text
credential
-> principal
-> explicit project
-> project lifecycle
-> current membership or audited platform entry
-> required capability
-> project-filtered repository operation
```

The server ignores a body `projectId` when the authenticated route or service principal already supplies project context. A mismatching body value is rejected.

## 7. Authentication and error semantics

- `401`: no valid credential, expired/revoked session, or disabled account.
- `403`: authenticated principal can see the project context but lacks the required capability.
- `404`: a resource is absent or belongs to a project the principal cannot inspect. This prevents identifier enumeration.
- `409`: revision conflict, last-owner removal, lifecycle conflict or incompatible assignment.
- `410`: optional explicit response for a previously known archived/revoked resource when disclosure is already authorized.

Membership, account state, platform role and project lifecycle are evaluated from current server state for protected requests. Permission reduction cannot wait for a cached token role or membership claim to expire. WebSockets and long-lived media sessions are closed or re-authorized when relevant membership, project or credential state changes.

## 8. Project and membership API baseline

The implementation supplies versioned equivalents of:

```text
GET/POST              /aiyoloapi/projects
GET/PATCH             /aiyoloapi/projects/{projectId}
POST                   /aiyoloapi/projects/{projectId}/suspend
POST                   /aiyoloapi/projects/{projectId}/archive
POST                   /aiyoloapi/projects/{projectId}/restore
GET/POST               /aiyoloapi/projects/{projectId}/members
PATCH/DELETE           /aiyoloapi/projects/{projectId}/members/{accountId}
POST                   /aiyoloapi/projects/{projectId}/transfer-owner
GET                    /aiyoloapi/auth/me
GET                    /aiyoloapi/auth/projects
GET/POST/PATCH         /aiyoloapi/platform/accounts...
GET/POST/PATCH/REVOKE  /aiyoloapi/projects/{projectId}/service-principals...
```

`auth/me` identifies the account and protocol version. Project membership and capability responses carry revisions so clients can discard stale state. Responses never expose password hashes, credential digests, session hashes or plain service credentials.

## 9. Realtime, media and evidence rules

- Alert, detection and notification WebSockets are project-qualified and authorize before accepting.
- Reconnect re-runs authorization and never reuses a previous project's subscription key.
- WHEP, LL-HLS, MJPEG and MediaMTX paths cannot reveal or attach to another project's stream with the same `streamId`.
- Stream creation, runtime restoration and deletion operate on `(projectId, streamId)`.
- Evidence lookup first resolves the event inside the current project, then resolves storage.
- Object-storage URLs are short lived and scoped to the authorized object; storage keys include an opaque project partition.
- Export jobs and files store project ownership and enforce it on status polling and download.

## 10. Audit contract

Security-relevant writes record:

- immutable audit ID and timestamp;
- request/correlation ID;
- actor account or service principal;
- platform role, project ID and effective project role;
- action and target type/ID;
- previous and new revision or a redacted change summary;
- outcome and safe failure code.

Audit payloads never contain passwords, session tokens, service credentials, signing keys, full RTSP credentials, original evidence bytes or remote-provider secrets. Platform project entry is itself audited.

## 11. Existing-data migration

Migration is staged and reversible until non-null constraints and new writes are enabled:

1. Preflight schema, row counts, duplicate external IDs, files and object evidence.
2. Back up database and evidence/model metadata with a tested restore point.
3. Add new identity, project and membership structures and nullable project columns.
4. Create one explicit default project with a recorded immutable ID.
5. Map existing admin accounts to `PLATFORM_ADMIN`; map existing operator accounts to `NORMAL_USER` and add reviewed default-project memberships.
6. Backfill every project-owned database row and evidence/storage reference.
7. Re-key uniqueness, runtime lookup and idempotency rules with project context.
8. Reconcile counts, hashes, orphan rows and referential integrity.
9. Enable project-aware dual-read/controlled compatibility for a bounded window.
10. Stop old global writes, require explicit context, and tighten non-null constraints.
11. Remove compatibility only after Android and admin clients meet the version gate.

The migration tool is idempotent, produces a dry-run report, checkpoints progress, fails closed on ambiguous ownership and documents rollback limits. It never assigns ambiguous rows to the first project silently.

## 12. Admin Web responsibilities

Platform administration provides project lifecycle, account lifecycle, membership assignment, owner transfer, global model governance and platform audit.

Project administration provides members, streams, rules, project model assignments, parameter overrides, verification/delivery settings, project audit and exports. All project pages retain a visible current-project signal. Switching project cancels requests, WebSockets, polling and media previews before clearing old state.

The Android app remains an inspection client, not a replacement for the administrative console.

## 13. Compatibility and version gates

- New clients advertise/require the project-context contract version.
- A new client talking to an old server stops with an upgrade-required state rather than making global requests.
- An old client is rejected or restricted once multi-project mode is activated; it is never granted an implicit project based on list order.
- A bounded default-project compatibility mode is allowed only before multiple active projects exist, must emit metrics/audit warnings, and has an explicit removal version.
- Legacy development tokens remain development-only and cannot bypass project authorization.

## 14. Security and acceptance matrix

The canonical fixture contains two projects, distinct owners and users, one platform administrator, one account with no membership, disabled identities, duplicate external resource IDs and project-bound service principals.

Tests cover list, single-resource and mutation endpoints; ID guessing; pagination; exports; model and evidence downloads; object storage; REST; WebSocket; WHEP; LL-HLS; MJPEG; stream ingest; mobile alert ingest; role changes; membership removal; project suspension/archive; concurrent project requests; session reuse; and browser multi-tab behavior.

Acceptance requires proof that a project A credential cannot read, write, subscribe to, download, infer the existence of, or cause side effects in project B. UI hiding without server denial fails acceptance.

## 15. Delivery sequence

Server M33-T02 through M33-T09 establish storage and authoritative authorization. M33-T10 through M33-T13 implement the management experience. M33-T14 through M33-T16 cover migration tooling, isolation testing and browser acceptance.

As explicitly requested on 2026-10-13, M33-T18 is the **local** joint gate with Android M100 and cannot pass from mocked clients alone. Its dependencies are T14/T15/T16 plus T22 (added 2026-10-14 for mobile legacy-ownership approval). Real local PostgreSQL, service processes, object/media services and built clients are sufficient; Docker/Kubernetes deployment is not a prerequisite. Android M100-T13 consumes this functional baseline, not a completed M33 major task. M100-T14 and T18 collect joint evidence without requiring the other task's completion status first.

M33-T17 depends on T14/T15/**T18** and retains all deployment, upgrade, backup/restore, security and rollback acceptance requirements. Local acceptance precedes container deployment acceptance; neither local tests nor isolated snapshot rehearsals authorize production migration or data disposition. M33 as a whole cannot close until both T18 and T17 have passed. See `docs/m33-local-acceptance-sequence.md` for the dependency decision and unchanged scope.

## 16. M33-T09 implementation addendum (2026-10-12)

The human roles above are unchanged. Owners and explicitly entered platform
administrators additionally have `project.service_principals.manage`; ordinary
project users do not. Non-human principals may only carry
`project.alerts.ingest` / `project.streams.ingest`, never human management
capabilities. See `docs/project-service-principals.md` for the machine request,
expiry, replay, one-time secret, rotation, audit and migration protocol.

Security exception to archived immutability: authorized owners/admins may revoke
a service credential in a suspended or archived project; no issue, edit, rotate
or business write is allowed there. Revocation never reactivates on restore.

## 17. Retired mobile legacy-data workflow

The historical M33 legacy-data ownership approval proposal is retired and is
not part of current project authorization or API behavior. The service no
longer exposes its routes or stores its approval tables. Historical task and
acceptance records remain under `harness/records/M33/`.

