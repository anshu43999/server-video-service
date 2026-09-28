from pathlib import Path
import re
import unittest

from app.main import app


ROOT = Path(__file__).resolve().parents[1]
OLD_API_PATH = re.compile(r"(?<!/)/api\b")


class ApiPrefixTests(unittest.TestCase):
    def test_registered_api_routes_use_aiyoloapi_prefix(self):
        def route_paths(routes):
            for route in routes:
                path = getattr(route, "path", None)
                if path is not None:
                    yield path
                included = getattr(route, "original_router", None)
                if included is not None:
                    yield from route_paths(included.routes)

        paths = list(route_paths(app.routes))
        api_paths = [path for path in paths if path.startswith("/aiyoloapi/")]
        self.assertTrue(api_paths)
        self.assertFalse([path for path in paths if OLD_API_PATH.search(path)])

    def test_runtime_clients_do_not_reference_legacy_api_prefix(self):
        for relative in (
            "app/static/app.js",
            "app/static/conversion.js",
            "tools/e2e_smoke.py",
            "tools/probe_output.py",
            "tools/push_video.py",
            "tools/verify_conversion_delivery.py",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(OLD_API_PATH.search(content), relative)


if __name__ == "__main__":
    unittest.main()
