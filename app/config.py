from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8080
    yolo_model_path: str = "models/yolo11n.pt"
    yolo_confidence: float = 0.25
    jpeg_quality: int = 80
    max_fps: float = 20.0
    mobile_token: str | None = None
    admin_token: str | None = None
    max_input_fps: float = 30.0
    max_output_subscribers: int = 4
    yolo_imgsz: int = 640
    yolo_device: str = "auto"
    yolo_classes: str | None = None
    yolo_overlay: bool = True
    mediamtx_rtsp_url: str = "rtsp://127.0.0.1:8554"
    # Optional HTTP origins for MediaMTX playback endpoints. When omitted,
    # origins are derived from the RTSP host and MediaMTX default ports.
    mediamtx_whep_url: str | None = None
    mediamtx_llhls_url: str | None = None
    mediamtx_http_scheme: str = "http"
    mediamtx_enabled: bool = False
    mediamtx_api_url: str | None = None
    mediamtx_ffmpeg_path: str | None = None
    mediamtx_video_encoder: str = "auto"
    mediamtx_reconnect_delay: float = 1.0
    mediamtx_max_reconnect_attempts: int = 3
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
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


settings = Settings()
