import importlib.util
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image

spec = importlib.util.spec_from_file_location("tiered_acceptance", Path(__file__).parents[1] / "tools/accept_tiered_alert_upload.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class TieredAcceptanceToolTests(unittest.TestCase):
    def test_deterministic_decodable_image_fixtures(self):
        for width, height, maximum in ((320, 180, 128 * 1024), (1280, 720, 5 * 1024**2)):
            content = acceptance.image(width, height)
            self.assertEqual(content, acceptance.image(width, height))
            self.assertLessEqual(len(content), maximum)
            with Image.open(BytesIO(content)) as decoded:
                self.assertEqual((width, height), decoded.size)
                decoded.verify()

    def test_cost_same_denominators_and_explicit_payload_bounds(self):
        cost = acceptance.cost_baseline()
        self.assertEqual(1000, cost["assumptions"]["eventsPerShift"])
        self.assertEqual(250, cost["assumptions"]["shiftsPerYear"])
        for name in ("compressed-primary", "maximum-original"):
            scenario = cost[name]
            self.assertEqual(scenario["tieredImageBytesPerShift"] * 250, scenario["tieredImageBytesPerYear"])
            self.assertAlmostEqual(1 - scenario["tieredImageBytesPerShift"] / scenario["legacyImageBytesPerShift"],
                                   scenario["savingFraction"])
            self.assertLess(scenario["tieredRemoteBytesAt90Days"], scenario["legacyRemoteBytesAt90Days"])


if __name__ == "__main__":
    unittest.main()
