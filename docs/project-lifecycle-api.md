# Project, account and membership lifecycle API

Admin UI and the platform-prefixed project aliases are documented in
`admin-project-management.md` (M33-T11). Read-only audit endpoints are
`GET /aiyoloapi/platform/audit` and `GET /aiyoloapi/projects/{projectId}/audit`,
with capability checks, scope-bound keyset cursors, and metadata-only responses.

These APIs implement the `m33-v1` project contract. Human clients authenticate
with a dynamic account session. Static development tokens remain limited to
legacy endpoints and cannot call these APIs.

## Platform APIs

`PLATFORM_ADMIN` is required for:

- `GET/POST /aiyoloapi/projects`
- `PATCH /aiyoloapi/projects/{projectId}`
- `POST /aiyoloapi/projects/{projectId}/suspend|archive|restore`
- `GET/POST /aiyoloapi/platform/accounts`
- `PATCH /aiyoloapi/platform/accounts/{accountId}`

Creating a project requires an explicit enabled `ownerAccountId`. A platform
administrator is not silently made a project member. The service prevents the
last enabled platform administrator from being disabled or demoted, and
prevents an account from being disabled while it is the last effective owner
of any project.

## Project membership APIs

An enabled project owner or an explicitly entering platform administrator can
use:

- `GET/POST /aiyoloapi/projects/{projectId}/members`
- `PATCH/DELETE /aiyoloapi/projects/{projectId}/members/{accountId}`
- `POST /aiyoloapi/projects/{projectId}/transfer-owner`

A project owner can add, update, disable and remove `PROJECT_USER` members.
They cannot grant `PROJECT_OWNER`, mutate another owner, or transfer ownership
from another account. `transfer-owner` atomically promotes the target and
demotes the source. Platform administrators may assign owner roles directly,
but the last enabled owner invariant still applies.

`GET /aiyoloapi/auth/projects` returns the caller's currently accessible
projects, role, membership/project revisions and effective capabilities.
Archived projects are hidden from ordinary project users; enabled owners retain
the frozen historical read capabilities. Platform administrators receive an
explicit `platformEntry` marker and still supply a project ID when entering a
project endpoint.

## Revisions and retries

Every mutable account, project and membership response carries `revision`.
PATCH, lifecycle and transfer requests carry the revision they observed. A
stale mutation returns `409 revision_conflict`; concurrent requests using the
same revision have exactly one winner.

An exact retry whose desired state is already current returns the current
resource without increasing its revision. Duplicate project codes and account
names return stable `409` errors. Re-adding an identical enabled membership
returns the existing membership; a differing duplicate must use PATCH.

Project transitions are:

```text
ACTIVE -> SUSPENDED -> ACTIVE
ACTIVE -> ARCHIVED  -> ACTIVE
SUSPENDED -> ARCHIVED
```

Repeating the current target state is a no-op. Suspending an archived project
returns `409 lifecycle_conflict`.

## Audit and correlation

Clients may send `X-Request-Id` (maximum 128 characters); otherwise the server
generates one. Project writes use `project_audit_events`; account writes use
`platform_audit_events`. Successful and domain-denied writes record actor,
platform/project role, target, revisions, safe before/after data, outcome and
failure code. Passwords, hashes, sessions and credentials are never audited.

A platform administrator passing a project capability dependency produces a
separate `project.platform_entry` audit event. It shares the request ID with
the project operation, allowing the entry and subsequent outcome to be traced
together.
