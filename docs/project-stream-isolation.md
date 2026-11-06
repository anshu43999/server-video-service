# Project-scoped video streams — current ADR-003 contract

Updated 2026-10-15 (M34-T04). Stream identity is `(project_id, stream_id)` across persisted configuration, runtime sessions, restore errors, model bindings, previews and alert sources. Duplicate stream IDs in different projects must never share data.

## Supported API

The explicit prefix is `/aiyoloapi/projects/{project_id}`.

| Method | Relative path | Purpose |
|---|---|---|
| POST / GET | `/streams` | Create / enumerate configured streams |
| DELETE | `/streams/{stream_id}` | Delete a configured stream and release its runtime |
| PATCH | `/streams/{stream_id}/config` | Persist parameters/enabled state |
| GET / PUT | `/streams/{stream_id}/model` | Bind an authorized project model release |
| POST | `/streams/{stream_id}/yolo` | Enable/disable analysis |
| GET | `/streams/{stream_id}/preview` | PC-only same-origin account-cookie JPEG snapshot |
| WS | `/streams/{stream_id}/ingest` | Authorized input, not a PC/mobile publishing UI |
| GET | `/capabilities/sources` | Project sources/capabilities for rules |

Control aliases without a project path are migration-only and require explicit project context or the separately approved bounded legacy window. Never guess a project from stream ID. New clients must use explicit project routes.

## Authorization

Platform administrators explicitly enter a project and that access is audited. PROJECT_OWNER maintains its sources and model bindings with the corresponding capabilities; PROJECT_USER may inspect sources, use authorized PC previews/models and consume alerts, but cannot maintain streams/model assignments. Ingest retains its separately checked human/service/device authorization; this does not restore Android remote video.

Preview requires `project.streams.view`, same-origin Session Cookie and no Bearer header, checked again after encoding. Anonymous/expired/revoked sessions, cross-project resources, suspended/archived projects and cross-site requests are rejected. This protects a channel, not a physical device identity.

## Preview and analysis

200 returns JPEG with `X-Preview-Mode: raw|yolo` and `Cache-Control: no-store, private`; no frame or input older than3seconds returns204. The UI clears old images on204/errors. Encoding is on demand, at most5fps and width1280; no H.264 process or media-server subscription. Model failure/YOLOoff keeps raw preview; stale/mismatched model results cannot be rendered.

YOLO/alert rules run independently of viewers. Structured results feed formal alert rules, persistence and protected evidence; clients consume formal alerts, not per-frame detections. Model release authorization remains checked. Switching projects cancels preview work and cannot show late frames from the prior project.

## Retired surfaces

Legacy and project `mjpeg/playback` return410 `live_video_retired`; `ws/detections` close1008 without resource lookup. `/aiyoloapi/internal/media/authorize` unconditionally returns403, including publish/api. No URL, internal credential, path parser or session-based media authorization remains.

Compatibility metrics `publish_state=retired`, `frames_published=0`, `viewers=0` do not indicate health or actual PC viewer counts. Do not alert on them.

## Persistence and upgrades

No stream schema migration or destructive data rewrite is introduced. Existing source types (including old websocket input), source URLs, model/version bindings, enabled state, parameters, revision and timestamps remain. Enabled streams restore normally; disabled records remain manageable. Retiring distribution does not delete SERVER_STREAM alerts, streamId provenance, images, stored short-video evidence, disposition or delivery history.

See [video protocol](video-protocol.md), [ADR-003](adr-003-analysis-alerts-only.md) and [upgrade/rollback](media-retirement-upgrade.md). Historical M33 media-path/authentication designs are superseded, not an alternate supported playback API.
