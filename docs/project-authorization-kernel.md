# Project authorization kernel

`app.auth` resolves a session to an immutable account identity. A session is
only a credential locator: every protected request reloads the account's
current enabled state and `platform_role`. The legacy `role` field remains a
temporary projection for existing endpoints and clients.

`app.project_auth` is the shared authorization boundary for new project-aware
HTTP and WebSocket endpoints. Endpoint code authorizes capabilities rather
than role strings:

```python
@router.post("/projects/{project_id}/streams")
async def create_stream(
    context: ProjectContext = Depends(require_project_capability(PROJECT_STREAMS_MANAGE)),
):
    ...
```

The resolver requires a project ID in `project_id`/`projectId` path parameters,
or temporarily in `X-Project-Id` for a compatibility endpoint. It never picks
the first or only project. Platform administrators must also provide this
explicit context; their `platform_entry` is marked on `ProjectContext` for the
audit integration added by the lifecycle APIs.

Each resolution reloads the project and membership. A disabled account yields
`401`, an absent or inaccessible project yields `404`, and a visible project
without the requested capability yields `403`. A missing explicit context
yields `400 project_context_required`.

Lifecycle capability policy:

- `ACTIVE`: use the full frozen role capability set.
- `SUSPENDED`: allow project/history reads and authorized membership/settings
  recovery; block inspection, stream/rule/model changes, alert disposition and
  exports.
- `ARCHIVED`: only a platform administrator or enabled project owner can read
  project and alert history/audit; ordinary member access and all writes stop.

Production never accepts static legacy client tokens. Development tokens keep
existing endpoint compatibility but are deliberately rejected by
`require_principal`, platform capability and project capability dependencies.
The database and memory implementations use the same account/project/member
resolution rules.

M33-T09 adds a separate machine boundary in `app.service_principals`. It does
not widen `require_principal` or `require_project_capability` to accept service
credentials. Only alert and stream ingestion opt into the machine resolver.
Owners/admins gain `project.service_principals.manage`; archived owners/admins
retain emergency credential revocation (not business writes). See
`docs/project-service-principals.md` for the scoped protocol and audit model.
