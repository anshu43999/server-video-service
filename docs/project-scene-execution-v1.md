# Project scene execution contract v1 (M36-T10 / M104-T06)

This extends scene configuration, not multi-model scheduling. Global model
`scenario` remains metadata; it is never substituted for the selected `sceneId`.

## Review and persistence

`POST /aiyoloapi/projects/{projectId}/scenes/{sceneId}/approval` with a current
`expectedRevision` freezes each member's exact project, modelId, version and
target platform (`mobile → android`, `pc → server`) profile. The profile includes
its real revision, inheritedRevision (when applicable), detection and alertRules.
Revision zero is accepted only when returned by the parameter store. It is not
a client fallback. No audit history or operator name is included in the profile.
The review audit retains before/after snapshots in the scene transaction.

Review takes the parameter process lock and the database default-project then
current-project row locks used by parameter writers. Reads occur after locks;
cross-worker writes therefore cannot split a reviewed profile. An edit, disable
or approval revocation clears snapshots and invalidates approval. Parameter edits
do not silently change reviewed scenes: explicit reapproval freezes fresh values
and increments scene revision. Clients cannot submit snapshots in member payloads.

This v1 execution contract is historical. The test-stage M33-T36 schema reset
does not migrate old scene records or scenario-scoped project assignments.
Current runtime selection requires an explicitly approved scene plan and
current project-model inventory authorization; see `project-scenes.md`.

## Catalog and runtime

Scene catalog/get responses advertise `executionContractVersion: 1`. A member
with an exact reviewed profile exposes `parameterPlatform`, `parameterRevision`
and `executionReady` (also requiring current availability). An available reviewed
member additionally exposes:

- `parameterSnapshot`: frozen profile with exact project/model/version/platform.
- `executionModel`: existing public model-catalog schema, retaining release,
  target readiness, signature and Android runtime contract gates. Only this
  member's target artifacts are included. Global/assignment download URL aliases
  are removed; URLs bind the scene and `expectedRevision` query.
- `parameterUrl`: `GET .../scenes/{sceneId}/models/{modelId}/versions/{version}/parameters?target=mobile&expectedRevision=N`.
  Response adds `sceneId` and `sceneRevision` to the frozen profile.

`POST .../scenes/{sceneId}/resolve` continues requiring inspection capability,
exact revision, requested target and supported image/video input. It resolves
one `single` member for that target. Missing reviewed parameters returns
`409 scene_parameters_not_approved`; sync/async or multiple members still return
`409 execution_mode_not_supported`. `resolutionOnly: true` means no server-side
inference or scheduling has been started.

Parameter and revision-bound artifact GETs recheck current project membership,
approval, release publication, target, artifact integrity and scene revision.
Stale revision is 409, unavailable/invisible resources are 404. Existing
unversioned scene artifact URLs remain compatible for previously supported
downloads; they are not execution grants and are not emitted in executionModel.
Scene-only authorization does not grant an old project assignment download or
parameter endpoint. Cached scenes/bytes alone must never authorize offline runs.

An Android consumer must bind project scope/generation, sceneId/revision, exact
model identity, Android profile revision and signed artifact hash together;
verify integrity and signature using the production installer; use the reviewed
parameters for image/Camera execution; and retire stale asynchronous callbacks.
Different scenes may review the same model at different parameter states.
