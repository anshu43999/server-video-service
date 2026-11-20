# M33-T09 validation — project-bound device/service credentials

Validated on 2026-10-12. Scope: server-video-service only; no Android changes,
production migration, service restart, Git commit or push.

## Delivered

- Independent DEVICE/SERVICE identity, immutable project binding, minimal
  alert-ingest / stream-ingest capabilities; no synthetic human account.
- Owner/platform-controlled issue, metadata lookup, revision-checked edit,
  rotation, terminal revocation and audit APIs. Plaintext secrets appear only
  on issue/rotation; stored values are digests.
- Current credential/project authorization for alert and WebSocket ingestion;
  human inspection sessions keep their existing membership-based access.
- Shared timestamp/nonce replay protection, restart persistence, immutable
  machine event retry behavior and per-principal event namespace.
- Revocation/rotation/expiry/capability/project changes stop subsequent stream
  messages; idle connections reauthorize every second. Internal ingest errors
  are not returned verbatim or published in stream status.
- Alert transactions recheck principal revision, current permissions and
  lifecycle; content-qualified evidence keys prevent conflicting overwrite.
- Migration 20261012_10, required-table startup validation, safe downgrade
  refusal when principals exist, SQLite/PostgreSQL coverage and operator docs.

## Final observed test results

| Check | Actual result | Evidence |
| --- | --- | --- |
| All ordinary tests, DATABASE_URL empty | 548 discovered; 520 passed, 28 skipped; 0 failures/errors; 156.415s | T09-full-suite.log |
| Credential API and WebSocket suite | 15 passed; 10.517s | T09-credential-api.log |
| Credential storage with RUN_POSTGRES_TESTS=1 | 15 passed: 9 PostgreSQL + 6 SQLite; 8.963s | T09-credential-postgresql.log |
| Existing model assignment storage regression | 8 passed: 5 PostgreSQL + 3 SQLite; 6.889s | T09-assignment-postgresql.log |
| PostgreSQL legacy migration round trip | 1 passed; 2.563s; no new metadata operations | T09-migration-postgresql.log |
| Harness unit tests | 30 passed; 0.055s | T09-harness.log |

The focused suites overlap the full suite; counts are not additive. PostgreSQL
integration tests use randomly named schemas and remove only their own schema.
The ordinary suite does not connect to the configured production database.
Compileall succeeded for changed Python product, migration and credential-test
files. Scoped git diff whitespace checks passed for edited tracked source/test
files. Harness validate passed before completion; complete/validate/render are
performed separately by CLI.

## Security evidence mapping

- tests/test_service_principals.py: ownership/capability denial, human-session
  separation, owner issuance, cross-project route/body rejection, evidence and
  disposition injection denial, secret redaction, last use, nonce reuse/stale
  timestamps, event retries/conflicts, expiry/rotation/revocation/CAS, lifecycle
  restrictions, upload-time revocation, handshake replay, same-project other
  device namespace rejection, idle socket closure and human membership removal.
- tests/test_service_principal_storage.py: digest-only persistence and audit
  actor FK correctness, replay after database reopen, current lifecycle checks,
  immutable event/human disposition preservation, transactional revocation
  recheck, competing rotations/nonces/events without the process-global lock,
  repeat migration, metadata alignment and nonempty downgrade refusal.

## Repairs made before the final green run

The first PostgreSQL run exposed missing timestamps in the test fixture; the
fixture now supplies the existing migration-required project timestamps. The
first full run reported two exact-set assertions that omitted the new tables
and owner capability; both were updated alongside the contract addendum. A
final security review replaced raw WebSocket exception disclosure with safe
messages and added a regression test. The final 548-test run includes this fix.

## Boundaries and remaining release work

- This completes the backend credential subtask only. M33-T10 onward and
  Android M100 / M33-T18 joint acceptance remain separate pending work.
- No production database or live client was upgraded. HTTPS/WSS, protected
  client secret storage and proxy log redaction are deployment requirements,
  not proven here by a real-device/live-proxy acceptance test.
- Bearer theft permits fresh authorized requests within the granted scope
  until revocation/expiry. Nonce protection does not claim proof-of-possession
  or mTLS; rotation/revocation is the response to leakage.
- An already accepted/executing frame may finish. Later messages are gated,
  and idle sockets check every second. Work is not retroactively undone.
- Evidence uploaded before a rejected/revoked write can remain unreferenced;
  retention handling is operational follow-up. No production objects were
  removed in this task.
- Memory mode is nonpersistent, single-process development/test storage.
- The test output contains existing dependency deprecation warnings and an
  intentional missing-model negative-test diagnostic; neither is reported as
  a test failure.

Protocol and operator instructions: docs/project-service-principals.md.
