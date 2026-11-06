from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    deployment_env: str = "development"
    admin_frontend_mode: Literal["vue"] = "vue"
    host: str = "0.0.0.0"
    port: int = 8080
    yolo_model_path: str = "models/yolo11n.pt"
    yolo_confidence: float = 0.25
    jpeg_quality: int = 80
    max_fps: float = 20.0
    mobile_token: str | None = None
    admin_token: str | None = None
    auth_session_days: int = 30
    # Retained only for database/config backward compatibility. The mobile
    # Opt-in, short-lived legacy route mapping; never used by explicit project routes.
    legacy_project_id: str | None = None
    legacy_project_until: str | None = None
    max_input_fps: float = 30.0
    rtsp_transport: str = "tcp"
    yolo_imgsz: int = 640
    yolo_device: str = "cpu"
    yolo_classes: str | None = None
    yolo_overlay: bool = True
    # Model marketplace download guardrails.  These limits protect the service
    # from exhausting file descriptors/bandwidth while remaining configurable
    # for local development and deployment sizing.
    model_download_max_concurrent: int = 2
    model_download_rate_limit: int = 10
    model_download_rate_window_seconds: float = 60.0
    model_download_chunk_size: int = 1024 * 1024
    # External Ed25519 PEM. Only the path and key id are configuration; key bytes
    # must never be persisted in model jobs or returned by an API.
    model_signing_key_id: str | None = None
    model_signing_private_key_path: str | None = None
    # Comma-separated key ids kept trusted during a rotation window. The
    # active signing key is always included implicitly.
    model_signing_trusted_key_ids: str | None = None
    # Comma-separated key ids that must never sign or make a release eligible.
    model_signing_revoked_key_ids: str | None = None
    database_url: str | None = None
    database_connect_timeout_seconds: int = 5
    # Operator-pinned Android SDK executables; never accepted from API input.
    app_apk_aapt2_path: str | None = None
    app_apk_java_path: str | None = None
    app_apk_apksigner_jar_path: str | None = None
    app_apk_evidence_root: str = "evidence/app-apk-verification"
    app_apk_staging_root: str = ".tmp/app-apk-verification"
    app_apk_max_bytes: int = 8 * 1024**3
    app_apk_tool_timeout_seconds: float = 60
    app_apk_upload_root: str = ".tmp/app-apk-uploads"
    app_apk_bucket: str = "aiyolo-app-apks"
    app_apk_object_prefix: str = "app-apks"
    app_apk_allowed_hosts: str = ""
    # Optional public HTTPS S3 gateway, distinct from the private upload endpoint.
    app_apk_download_endpoint: str | None = None
    # Operator-owned trusted CI compatibility JSON, never from an APK form.
    app_apk_compatibility_path: str | None = None
    app_apk_max_jobs: int = 4
    app_apk_receive_seconds: int = 300
    app_apk_lease_seconds: int = 1800
    app_apk_worker_enabled: bool = False
    app_apk_external_enabled: bool = False
    app_apk_external_root: str = ".tmp/app-apk-external"
    app_apk_external_seconds: int = 300
    # App metadata signing is independent of model/APK signing identities.
    app_updates_enabled: bool = False
    app_update_key_id: str | None = None
    app_update_private_key_path: str | None = None
    app_update_scopes_path: str | None = None
    # Operator-owned, hash-bound CI evidence; never supplied by browser forms.
    app_update_recovery_evidence_path: str | None = None
    app_update_server_contract_version: int = 1
    app_update_gate_capabilities: str = ""
    app_update_max_devices: int = 100000
    app_update_max_receipts_per_device: int = 10000
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "aiyolo-alerts"
    minio_secure: bool = True
    minio_region: str | None = None
    minio_alert_prefix: str = "alerts"
    minio_auto_create_bucket: bool = False
    alert_evidence_retention_days: int = 90
    alert_evidence_delete_grace_hours: int = 24
    calibration_root: str = "calibration"
    calibration_max_upload_bytes: int = 512 * 1024 * 1024
    calibration_max_expanded_bytes: int = 2 * 1024 * 1024 * 1024
    calibration_max_files: int = 5000
    # Old MEDIAMTX_*/MAX_OUTPUT_SUBSCRIBERS keys are ignored on upgrades;
    # no setting can restore the retired publishing/playback paths.
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    @field_validator("yolo_device", mode="before")
    @classmethod
    def use_cpu_device(cls, value: str) -> str:
        # Old deployments may still supply auto/cuda/numeric device settings.
        # Keep upgrades working while enforcing the CPU-only runtime policy.
        return "cpu"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        if value and not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("DATABASE_URL must use PostgreSQL with the psycopg driver")
        return value

    @field_validator("rtsp_transport")
    @classmethod
    def validate_rtsp_transport(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"tcp", "udp"}:
            raise ValueError("RTSP_TRANSPORT must be tcp or udp")
        return normalized


settings = Settings()
