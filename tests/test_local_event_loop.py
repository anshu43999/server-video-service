"""Isolated loopback regression; never import the business app or its settings."""
import asyncio
from pathlib import Path
import runpy
import socket
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import uvicorn

from app.local_event_loop import create_windows_loop, local_uvicorn_loop


ROOT = Path(__file__).resolve().parents[1]


async def test_app(scope, receive, send):
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"2")]})
        await send({"type": "http.response.body", "body": b"ok"})
    elif scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
        while (await receive())["type"] != "websocket.disconnect":
            pass


class LocalEventLoopTests(unittest.TestCase):
    def test_non_windows_keeps_uvicorn_auto(self):
        with patch("app.local_event_loop.sys.platform", "linux"):
            self.assertEqual(local_uvicorn_loop(), "auto")

    def test_run_entry_passes_local_loop_without_importing_business_app(self):
        with patch.dict(sys.modules, {"app.config": SimpleNamespace(
            settings=SimpleNamespace(host="127.0.0.1", port=8765)
        )}), patch("uvicorn.run") as run:
            runpy.run_path(str(ROOT / "run.py"), run_name="__main__")
        run.assert_called_once_with(
            "app.main:app", host="127.0.0.1", port=8765,
            reload=False, loop=local_uvicorn_loop(),
        )

    def test_powershell_normal_and_reload_select_same_loop(self):
        text = (ROOT / "start-server.ps1").read_text(encoding="utf-8")
        launches = [line.strip() for line in text.splitlines()
                    if "& $venvPython -m uvicorn " in line]
        self.assertEqual(len(launches), 2)
        for line in launches:
            self.assertIn("--loop app.local_event_loop:create_windows_loop", line)
            self.assertIn("--port $Port", line)
        self.assertEqual(sum("--reload" in line for line in launches), 1)

    @unittest.skipUnless(sys.platform == "win32", "Windows-specific regression")
    def test_uvicorn_selects_selector_with_and_without_reload(self):
        for reload in (False, True):
            config = uvicorn.Config(
                "app.main:app", loop=local_uvicorn_loop(), reload=reload,
            )
            loop = config.get_loop_factory()()
            try:
                self.assertIsInstance(loop, asyncio.SelectorEventLoop)
                self.assertNotIsInstance(loop, asyncio.ProactorEventLoop)
            finally:
                loop.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows-specific regression")
    def test_aborted_http_and_websocket_connections_keep_listener_alive(self):
        with asyncio.Runner(loop_factory=create_windows_loop) as runner:
            runner.run(self._exercise_disconnects())

    async def _exercise_disconnects(self):
        loop = asyncio.get_running_loop()
        errors = []
        loop.set_exception_handler(lambda _, context: errors.append(context))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.setblocking(False)
        address = listener.getsockname()
        server = uvicorn.Server(uvicorn.Config(
            test_app, lifespan="off", access_log=False, log_level="error",
            loop=local_uvicorn_loop(),
        ))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if serving.done():
                        await serving
                        self.fail("isolated server exited before becoming ready")
                    await asyncio.sleep(0.01)
                for _ in range(20):
                    # Abort during incomplete HTTP parsing.
                    _, writer = await asyncio.open_connection(*address)
                    writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n")
                    await writer.drain()
                    writer.get_extra_info("socket").setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0)
                    )
                    writer.transport.abort()
                    await asyncio.sleep(0)
                for _ in range(10):
                    reader, writer = await asyncio.open_connection(*address)
                    writer.write(
                        b"GET / HTTP/1.1\r\nHost: localhost\r\n"
                        b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        b"Sec-WebSocket-Version: 13\r\n"
                        b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
                    )
                    await writer.drain()
                    self.assertIn(b" 101 ", await reader.readuntil(b"\r\n\r\n"))
                    writer.get_extra_info("socket").setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0)
                    )
                    writer.transport.abort()
                    await asyncio.sleep(0)
                for _ in range(5):
                    reader, writer = await asyncio.open_connection(*address)
                    writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    response = await reader.read()
                    self.assertIn(b" 200 ", response)
                    self.assertTrue(response.endswith(b"ok"))
                    writer.close()
                    await writer.wait_closed()
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(serving, 5)
            finally:
                listener.close()
        self.assertFalse(errors, errors)
        self.assertEqual(listener.fileno(), -1)


if __name__ == "__main__":
    unittest.main()
