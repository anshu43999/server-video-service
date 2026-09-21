from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConverterSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8090
    token: str = ""
    root: Path = Path("/data")
    calibration_root: Path = Path("/calibration")
    builtin_calibration_manifest: Path = Path("/app/calibration-builtin/manifest.json")
    max_upload_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    max_queued_jobs: int = Field(default=20, ge=1, le=1000)
    timeout_seconds: int = Field(default=3600, ge=30, le=14400)
    model_config = SettingsConfigDict(env_prefix="CONVERTER_", extra="ignore")


settings = ConverterSettings()
