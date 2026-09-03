"""Stable protocol constants shared by the HTTP/WebSocket handlers."""

from enum import StrEnum


class StreamState(StrEnum):
    CREATED = "created"
    INGESTING = "ingesting"
    OUTPUTTING = "outputting"
    ERROR = "error"
    CLOSED = "closed"


class YoloState(StrEnum):
    OFF = "off"
    ON = "on"


MAX_FRAME_BYTES = 5 * 1024 * 1024
MAX_FRAME_WIDTH = 1920
MAX_FRAME_HEIGHT = 1080
MAX_INPUT_FPS = 30.0
SUPPORTED_IMAGE_FORMATS = ("jpeg", "png")
MOBILE_AUTH_HEADER = "X-Video-Service-Token"
ADMIN_AUTH_SCHEME = "Bearer"


ERROR_CODES = {
    "stream_not_found": (404, False),
    "stream_already_exists": (409, False),
    "invalid_frame": (400, False),
    "frame_too_large": (413, False),
    "input_rate_limited": (429, True),
    "model_unavailable": (503, True),
    "internal_error": (500, True),
}


class InputRateLimitError(ValueError):
    """Raised when a client sends frames faster than the configured limit."""
