"""Alert engine implementation of docs/alert-engine-spec.md (spec version v1).

The engine is model-agnostic and scenario-agnostic: no business class name may
appear in this package (spec §1).  Scenario packs inject labels, ROIs and
thresholds from the outside.
"""

SPEC_VERSION = "v1"

from .observation import (
    Classification,
    Mask,
    NonMonotonicTimestampError,
    Observation,
    ObservationEnvelope,
    ObservationError,
    ObservationIngestor,
    Rejection,
    Scalar,
    check_operator_compatibility,
    ingest_observation,
    validate_operator_compatibility,
)
from .engine import run_vector
from .lifecycle import EventRecord, EventStateMachine
from .rules import RuleRegistry, RuleValidationError, rule_registry
from .disposition import (AlertDispositionStore, DispositionStore, DispositionAction,
                          alert_disposition_store, sanitise_training_entry, sanitize_training_entry)
from .delivery import (
    AlertDeliveryService,
    AlertDispatcher,
    AppNotificationChannel,
    DeliveryError,
    DeliveryReceipt,
    EmailChannel,
    EnterpriseIMChannel,
    EmailAdapter,
    EnterpriseIMAdapter,
    SmsChannel,
    ManagementPageChannel,
    SmsAdapter,
)

__all__ = [
    "SPEC_VERSION", "Classification", "Mask", "Scalar", "Observation", "ObservationEnvelope",
    "ObservationError", "NonMonotonicTimestampError", "ObservationIngestor", "Rejection",
    "ingest_observation", "validate_operator_compatibility", "check_operator_compatibility",
    "run_vector", "EventRecord", "EventStateMachine", "RuleRegistry", "RuleValidationError", "rule_registry",
    "AlertDispositionStore", "DispositionStore", "DispositionAction", "alert_disposition_store",
    "sanitise_training_entry", "sanitize_training_entry",
    "AlertDeliveryService", "AlertDispatcher", "AppNotificationChannel", "DeliveryError",
    "DeliveryReceipt", "EmailAdapter", "EnterpriseIMAdapter", "ManagementPageChannel", "SmsAdapter",
    "EmailChannel", "EnterpriseIMChannel", "SmsChannel",
]
