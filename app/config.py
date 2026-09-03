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
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


settings = Settings()
