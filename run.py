import uvicorn

from app.local_event_loop import local_uvicorn_loop


if __name__ == "__main__":
    from app.config import settings

    uvicorn.run(
        "app.main:app", host=settings.host, port=settings.port,
        reload=False, loop=local_uvicorn_loop(),
    )
