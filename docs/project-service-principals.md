# Project-bound device and service credentials

Implementation: M33-T09; migration head: `20261012_10`. This extends the frozen
M33 identity contract without changing human account sessions.

## Identity and authority

- `DEVICE` / `SERVICE` are non-human identities, not account roles. An immutable
  `principalId` belongs to exactly one immutable `projectId`. There is no account
  session, synthetic account, membership, or platform role behind a machine.
- Owners and explicitly entered platform administrators manage credentials with
  `project.service_principals.manage`. Ordinary project users cannot issue, edit,
  rotate, revoke, enumerate or audit them.
- Only `project.alerts.ingest` and `project.streams.ingest` may be granted. Neither
  grants alert reads/disposition, members, settings, model governance, stream
  creation, or platform access. A credential can carry either or both.
- Existing human inspection users continue using short-lived account sessions
  and their current project membership. They cannot write another project.
- Suspended and archived projects cannot ingest. Issue/edit/rotate require an
  active project. Owners/admins retain audit visibility and emergency revocation
  for suspended/archived projects; restoring a project never restores revoked
  credentials. Revocation is terminal; issue a new identity when appropriate.

## Management endpoints

Base: `/aiyoloapi/projects/{projectId}/service-principals`

| Method and suffix | Request / result |
| --- | --- |
| POST base | `displayName`, `principalType`, `capabilities`, `expiresAt`; 201 |
| GET base | Project-scoped `principals`, never digests or credentials |
| GET `/{principalId}` | Metadata including revision, expiry, revocation, last use |
| PATCH `/{principalId}` | `expectedRevision` plus changed name/capabilities/expiry |
| POST `/{principalId}/rotate` | `expectedRevision`, `expiresAt`; old secret immediately invalid |
| POST `/{principalId}/revoke` | `expectedRevision`; terminal revocation |
| GET `/{principalId}/audit` | `offset` (default 0), `limit` (1–200; default 100) |

Expiry must include a timezone, be in the future and at most 365 days away. Use
the shortest practical lifetime. All mutation bodies reject unknown fields;
project/type/ID cannot be rebound through PATCH. Revision conflicts return 409.

Creation and rotation return `credential` exactly once with `tokenType=Bearer`.
Store it in the device/service secret store immediately. Responses use
`Cache-Control: no-store` and `Pragma: no-cache`. Only SHA-256 of a random
384-bit secret-bearing token is stored. List/detail/audit never retrieve it.
Lost responses are handled by a fresh revision-checked rotation, not retrieval.

## Machine request protocol

Send the following headers over HTTPS/WSS:

```text
Authorization: Bearer <credential returned once>
X-Service-Timestamp: <UTC Unix time in integer seconds>
X-Service-Nonce: <new random 16–128 character A–Z/a–z/0–9/_/- value>
```

Use explicit project paths. Compatibility paths still require `X-Project-Id`.
No project is inferred from list order, and a credential can never override its
stored project binding. Cross-project requests return 404. An explicit body
`projectId` different from the authenticated project returns 409. Query-string,
cookie and legacy-token headers are not machine credential channels.

Timestamps must be within ±300 seconds. A nonce is used once per principal
across both ingest transports, including reconnects. Its digest is stored with
the project and principal until the complete acceptance window ends. PostgreSQL
uniqueness and row locks enforce this across app workers and restarts. Identical
nonce reuse returns 409; stale/missing replay headers return 401. Expired nonce
records are removed on subsequent authenticated requests. Memory mode is only
single-process, non-persistent development/test storage.

### Alert ingestion

POST `/aiyoloapi/projects/{projectId}/alerts/mobile-ingest` requires
`project.alerts.ingest` for machines. The ordinary mobile event fields remain,
with these additional non-human rules:

- `eventId` must begin `service:{principalId}:` and have a stable unique suffix.
  Another machine or a human ingest request cannot claim this namespace.
- Machine events are immutable. Retry an identical payload with a **new nonce**
  and the same eventId; the response is 202 with `created=false`. Changed content
  under the same eventId returns 409. A new observation requires a new eventId.
- Machines cannot submit `disposition`. Evidence may contain only
  `snapshotDataUrl`; arbitrary existing object references/URLs are rejected.
- Project ownership is server-derived. Event storage rechecks the current
  credential revision, expiry, revocation, capability and project lifecycle
  inside the PostgreSQL write transaction. This serializes with revocation and
  project lifecycle changes. Upload completion is reauthorized as well.
- Evidence keys include project partition, event and content fingerprint.
  Conflicting concurrent uploads cannot overwrite an accepted event's evidence.
  Failed/revoked uploads may leave unreferenced objects for the existing retention
  process; this task never deletes production evidence.
- The response contains only `accepted`, `created`, `eventId`, `projectId`;
  ingest permission does not expose later human dispositions or evidence reads.

### WebSocket ingestion

Connect to `/aiyoloapi/projects/{projectId}/streams/{streamId}/ingest` with
`project.streams.ingest`. The target stream must already exist in that project.
Fresh timestamp/nonce headers are mandatory for each handshake.

The server reauthorizes before every received message and checks idle sockets
every second. Expiry, revocation and rotation close with 4401; missing/invisible
project with 4404; capability reduction or inactive project with 4403. Human
connections also re-read session/account/membership state. Work already accepted
before revocation is not retroactively undone. A frame currently executing may
finish; no later messages pass the next authorization check. Last-used time is
the last authorized HTTP request or WebSocket handshake (not every video frame).

## Audit and leakage response

Issue/edit/rotate/revoke record actor account, project, revision and redacted
change fields. Machine use/ingest and attributable denial records set
`actorServicePrincipalId`, leaving `actorAccountId` null. Unknown/invalid secrets
do not fabricate an audit identity. No plaintext credential or digest is included
in audit changes. Never configure proxy/access logs to record Authorization,
cookies, one-time credential response bodies, or complete request headers.

If a credential leaks: revoke immediately or rotate using the current revision;
confirm old requests fail, inspect principal audit/last-use metadata, provision
the replacement securely, and investigate the owning project. A stolen bearer
can act within its own granted capabilities until revoked/expired. Timestamp
and nonce rejection stops captured-request replay, **not** an attacker who owns
the bearer and generates fresh requests. This release does not claim mTLS or
cryptographic proof-of-possession. TLS and protected secret storage are required.

## Migration and acceptance boundary

`20261012_10` adds `service_principals` and `service_request_nonces`; it does not
change or automatically convert existing human sessions. Schema startup checks
require both tables. Upgrade is tested twice, metadata alignment is checked, and
downgrade refuses to drop a schema containing any principal. Empty-schema
downgrade/re-upgrade remains supported. Review and back up before deployment;
this task's tests migrate random PostgreSQL schemas only, never production.

Executable evidence lives in `tests/test_service_principals.py` and
`tests/test_service_principal_storage.py`. These cover memory, SQLite and real
PostgreSQL, including cross-worker lock/CAS/replay tests, plus existing mobile
and project regressions. Web UI/Android credential provisioning, live TLS proxy
behavior and real-device end-to-end acceptance remain later M33/M100 work; this
backend task does not claim the entire multi-project release is complete.
