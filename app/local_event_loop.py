"""Event loop for the Windows local development launcher."""
import asyncio
import sys


def create_windows_loop() -> asyncio.AbstractEventLoop:
    # IOCP accept errors (e.g. WinError 64) can close the listening socket
    # in CPython's Proactor loop. Local Windows runs use socket selection.
    # Do not use this for high-concurrency Windows production deployments:
    # SelectSelector is limited to 512 sockets and has no asyncio subprocesses.
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


def local_uvicorn_loop() -> str:
    return "app.local_event_loop:create_windows_loop" if sys.platform == "win32" else "auto"
