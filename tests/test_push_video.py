import unittest

from tools.push_video import build_parser, parse_source


class PushVideoToolTests(unittest.TestCase):
    def test_parse_camera_and_path_sources(self):
        self.assertEqual(parse_source("0"), 0)
        self.assertEqual(parse_source("sample.mp4"), "sample.mp4")

    def test_parser_requires_stream_and_source(self):
        args = build_parser().parse_args(["--stream-id", "demo", "--source", "0"])
        self.assertEqual(args.stream_id, "demo")
        self.assertEqual(args.source, "0")
        self.assertEqual(args.quality, 80)


if __name__ == "__main__":
    unittest.main()
