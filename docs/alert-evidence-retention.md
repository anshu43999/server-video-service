# Alert evidence retention (M37-T04)

Tiered evidence references are retained for 90 days from `uploadedAt`. An operator
may set an explicit sample-retention marker for a particular evidence version;
the marker must expire within 365 days of upload and is recorded in the platform
audit log. `FALSE_POSITIVE` alone never extends retention. Apply one explicitly
with `tools/retain_alert_evidence.py`, supplying the project/event/evidence
identity, a timezone-aware `--until`, and the operator `--actor`.

The cleanup command is dry-run by default:

```powershell
python tools/cleanup_alert_evidence.py --batch-size 100
python tools/cleanup_alert_evidence.py --apply --batch-size 100
```

Use the returned `nextAfter` pair as `--after-project-id` and `--after-event-id`
to continue bounded scans. Configure `ALERT_EVIDENCE_RETENTION_DAYS` (default
90, maximum 365) and `ALERT_EVIDENCE_DELETE_GRACE_HOURS` (default 24, maximum
168). A cleanup run first marks eligible references `DELETE_PENDING`; a later
run, after the grace period, rechecks the event reference, retention marker,
shared object references, and event-row lock before deleting from the configured
MinIO bucket. Reads hold that same database row lock through object retrieval.
Failed deletes remain pending for a later retry; successful deletes retain a
tombstone and remove the object reference from the event payload.

The job never sweeps an object-store prefix. Unreferenced legacy objects and
references without a trustworthy upload timestamp are reported/skipped and
require explicit reconciliation; they are never assigned an inferred age.
