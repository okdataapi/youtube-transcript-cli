"""Runs yt_transcript.py against a local mock of the okdata API. No network, no real key."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
os.environ["NO_PROXY"] = "*"

import yt_transcript as yt  # noqa: E402
from mock_okdata import TEST_KEY, MockOkdata, error, ok  # noqa: E402

VID = "dQw4w9WgXcQ"
TRANSCRIPT = {"video_id": VID, "lang": "en", "text": "Hello there. General Kenobi.",
              "segments": [{"start": 0.0, "end": 1.5, "text": "Hello there."}, {"start": 3725.5, "end": 3727.25, "text": "General Kenobi."}]}


class VideoIdTest(unittest.TestCase):
    def test_link_shapes(self) -> None:
        for link in [VID, f"https://www.youtube.com/watch?v={VID}&t=42s", f"https://youtu.be/{VID}?si=abc", f"youtube.com/shorts/{VID}",
                     f"https://m.youtube.com/watch?feature=share&v={VID}", f"https://www.youtube.com/live/{VID}", f"https://www.youtube-nocookie.com/embed/{VID}"]:
            self.assertEqual(yt.video_id(link), VID, link)

    def test_rejects_other_sites_and_junk(self) -> None:
        for bad in ["https://example.com/watch?v=" + VID, "https://www.youtube.com/channel/UC123", "short", "https://evil.com/youtu.be/" + VID]:
            with self.assertRaises(ValueError, msg=bad):
                yt.video_id(bad)


class RenderTest(unittest.TestCase):
    def test_formats(self) -> None:
        self.assertEqual(yt.render(TRANSCRIPT, "txt"), "Hello there. General Kenobi.\n")
        srt = yt.render(TRANSCRIPT, "srt")
        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\nHello there.\n", srt)
        self.assertIn("2\n01:02:05,500 --> 01:02:07,250\nGeneral Kenobi.\n", srt)
        self.assertTrue(yt.render(TRANSCRIPT, "vtt").startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.500"))
        md = yt.render(TRANSCRIPT, "md")
        self.assertIn(f"- [1:02:05](https://youtu.be/{VID}?t=3725) General Kenobi.", md)
        self.assertEqual(json.loads(yt.render(TRANSCRIPT, "json"))["lang"], "en")


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api = MockOkdata({"/v1/youtube/videos/transcript/get": lambda q: (404, error("not_found")) if q["id"] == "aaaaaaaaaaa"
                               else (200, ok("t", item={**TRANSCRIPT, "video_id": q["id"]}, amount="0.004"))})
        yt.API = self.api.url
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.api.close()
        self.tmp.cleanup()

    def run_cli(self, *argv: str, key: str = TEST_KEY) -> tuple:
        os.environ["OKDATA_API_KEY"] = key
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = yt.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_prints_text_and_sends_lang(self) -> None:
        code, out, log = self.run_cli(f"https://youtu.be/{VID}", "--lang", "en")
        self.assertEqual(code, 0, log)
        self.assertEqual(out, "Hello there. General Kenobi.\n")
        self.assertEqual(self.api.requests[0]["query"], {"id": VID, "lang": "en"})
        self.assertIn("spent $0.004", log)

    def test_several_videos_go_to_a_folder_and_duplicates_are_fetched_once(self) -> None:
        folder = Path(self.tmp.name) / "out"
        code, _, log = self.run_cli(VID, f"https://youtu.be/{VID}", "bbbbbbbbbbb", "--format", "srt", "-o", str(folder))
        self.assertEqual(code, 0, log)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([f"{VID}.srt", "bbbbbbbbbbb.srt"]))
        self.assertEqual(len(self.api.requests), 2)

    def test_single_file_output(self) -> None:
        target = Path(self.tmp.name) / "talk.vtt"
        self.assertEqual(self.run_cli(VID, "--format", "vtt", "-o", str(target))[0], 0)
        self.assertTrue(target.read_text(encoding="utf-8").startswith("WEBVTT"))

    def test_failures_budget_dry_run_and_key(self) -> None:
        code, _, log = self.run_cli("aaaaaaaaaaa", VID)
        self.assertEqual(code, 0)
        self.assertIn("aaaaaaaaaaa: not_found", log)
        self.assertEqual(self.run_cli("aaaaaaaaaaa")[0], 1)
        self.assertEqual(self.run_cli(VID, "--budget", "0.001")[0], 3)
        self.assertEqual(self.run_cli(VID, "--dry-run", key="")[0], 0)
        code, _, log = self.run_cli(VID, key="")
        self.assertEqual(code, 2)
        self.assertIn("src=gh-youtube-transcript-cli", log)
        code, _, log = self.run_cli(VID, "bbbbbbbbbbb", key="okd_wrong")
        self.assertEqual(code, 1)
        self.assertIn("unauthorized", log)
        self.assertEqual(sum(1 for r in self.api.requests if "okd_wrong" in r["headers"]["authorization"]), 1)  # stopped at once

    def test_a_malformed_answer_is_saved_raw_not_lost(self) -> None:
        self.api.routes["/v1/youtube/videos/transcript/get"] = lambda q: (200, ok("t", item={"video_id": VID, "segments": [{"text": "no times"}]}, amount="0.004"))
        folder = Path(self.tmp.name) / "raw"
        code, _, log = self.run_cli(VID, "bbbbbbbbbbb", "--format", "srt", "-o", str(folder))
        self.assertEqual(code, 0)
        self.assertIn("saved the raw JSON instead", log)
        self.assertEqual(sorted(p.suffix for p in folder.iterdir()), [".json", ".json"])

    def test_bad_input_exits_with_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(io.StringIO()):
            yt.main(["https://vimeo.com/123"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
