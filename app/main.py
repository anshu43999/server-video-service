from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .stream import StreamSession
from .protocol import ERROR_CODES, InputRateLimitError, StreamState
from .auth import require_admin, require_mobile
from .config import settings
from .metrics import system_metrics
from .model_catalog import ModelCatalog

streams: dict[str, StreamSession] = {}
model_catalog = ModelCatalog()


class CreateStreamRequest(BaseModel):
    stream_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    source_url: str | int | None = None


class YoloRequest(BaseModel):
    enabled: bool


class StreamConfigRequest(BaseModel):
    confidence: float | None = Field(default=None, ge=0.01, le=0.99)
    max_fps: float | None = Field(default=None, ge=1, le=60)
    yolo_enabled: bool | None = None


class RegisterManifestRequest(BaseModel):
    manifest_path: str = Field(min_length=1, max_length=512)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await asyncio.gather(*(stream.close() for stream in streams.values()), return_exceptions=True)


app = FastAPI(title="Server Video Service", version="0.1.0", lifespan=lifespan)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/admin", StaticFiles(directory=STATIC_DIR, html=True), name="admin")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(STATIC_DIR / "index.html")


def get_stream(stream_id: str) -> StreamSession:
    stream = streams.get(stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="stream not found")
    return stream


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "streams": len(streams)}


@app.get("/api/metrics")
async def metrics():
    return {"system": system_metrics(), "streams": {stream_id: stream.metrics() for stream_id, stream in streams.items()}}


@app.get("/api/models")
async def list_models(_: None = Depends(require_admin)):
    return {"models": model_catalog.list_models()}


@app.post("/api/models/{model_id}/activate")
async def activate_model(model_id: str, _: None = Depends(require_admin)):
    try:
        model = model_catalog.activate(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"active_model": model}


@app.post("/api/models/register")
async def register_models(request: RegisterManifestRequest, _: None = Depends(require_admin)):
    try:
        models = model_catalog.register_manifest(request.manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"models": models}


@app.post("/api/streams", status_code=201, dependencies=[Depends(require_admin)])
async def create_stream(request: CreateStreamRequest):
    if request.stream_id in streams:
        raise HTTPException(status_code=ERROR_CODES["stream_already_exists"][0], detail="stream already exists")
    source = request.source_url
    if isinstance(source, str) and source.isdigit():
        source = int(source)
    stream = StreamSession(request.stream_id, source)
    stream.detector.model_path = model_catalog.active_server_path()
    streams[request.stream_id] = stream
    await stream.start()
    return {
        "stream_id": stream.stream_id,
        "state": stream.state,
        "yolo_enabled": stream.yolo_enabled,
    }


@app.get("/api/streams")
async def list_streams():
    return [
        {
            "stream_id": s.stream_id,
            "state": s.state,
            "yolo_enabled": s.yolo_enabled,
            **s.metrics(),
            "last_error": s.last_error,
            "confidence": s.detector.confidence,
            "max_fps": s.max_fps,
            "model": s.detector.metadata(),
        }
        for s in streams.values()
    ]


@app.delete("/api/streams/{stream_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_stream(stream_id: str):
    stream = get_stream(stream_id)
    await stream.close()
    streams.pop(stream_id, None)


@app.post("/api/streams/{stream_id}/yolo", dependencies=[Depends(require_admin)])
async def set_yolo(stream_id: str, request: YoloRequest):
    stream = get_stream(stream_id)
    await stream.set_yolo(request.enabled)
    return {
        "stream_id": stream_id,
        "state": stream.state,
        "yolo_enabled": stream.yolo_enabled,
        "model_error": stream.detector.load_error,
        "model": stream.detector.metadata(),
    }


@app.patch("/api/streams/{stream_id}/config", dependencies=[Depends(require_admin)])
async def update_stream_config(stream_id: str, request: StreamConfigRequest):
    stream = get_stream(stream_id)
    if request.confidence is not None:
        stream.detector.confidence = request.confidence
    if request.max_fps is not None:
        stream.max_fps = request.max_fps
    if request.yolo_enabled is not None:
        await stream.set_yolo(request.yolo_enabled)
    return {
        "stream_id": stream_id,
        "state": stream.state,
        "yolo_enabled": stream.yolo_enabled,
        "confidence": stream.detector.confidence,
        "max_fps": stream.max_fps,
        "model_error": stream.detector.load_error,
        "model": stream.detector.metadata(),
    }


@app.websocket("/api/streams/{stream_id}/ingest")
async def ingest(stream_id: str, websocket: WebSocket):
    stream = streams.get(stream_id)
    if stream is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    if settings.mobile_token:
        token = websocket.headers.get("x-video-service-token")
        if token != settings.mobile_token:
            await websocket.close(code=4401, reason="mobile token required")
            return
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await stream.ingest_jpeg(message["bytes"])
            elif message.get("text"):
                await websocket.send_text(json.dumps({"ok": True}))
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception as exc:
        stream.last_error = str(exc)
        code = 4429 if isinstance(exc, InputRateLimitError) else 4400
        await websocket.close(code=code, reason=str(exc))


async def mjpeg_generator(stream: StreamSession):
    previous = None
    while True:
        frame = await stream.wait_frame(previous)
        if frame is None:
            return
        previous = frame
        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"


@app.get("/api/streams/{stream_id}/mjpeg")
async def mjpeg(stream_id: str):
    stream = get_stream(stream_id)
    if not stream.try_subscribe():
        raise HTTPException(status_code=429, detail="output subscriber limit reached")

    async def guarded_generator():
        try:
            async for frame in mjpeg_generator(stream):
                yield frame
        finally:
            stream.unsubscribe()

    return StreamingResponse(guarded_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/api/streams/{stream_id}/ws")
async def output_ws(stream_id: str, websocket: WebSocket):
    stream = streams.get(stream_id)
    if stream is None:
        await websocket.close(code=4404)
        return
    if not stream.try_subscribe():
        await websocket.close(code=4429, reason="output subscriber limit reached")
        return
    await websocket.accept()
    previous = None
    try:
        while True:
            frame = await stream.wait_frame(previous)
            if frame is None:
                return
            previous = frame
            await websocket.send_bytes(frame)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        stream.unsubscribe()
