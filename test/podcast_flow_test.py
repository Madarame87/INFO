import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "flows" / "podcast-bookmarks.py"


def import_flow(home):
    old_home = os.environ.get("HOME")
    old_argv = sys.argv[:]
    os.environ["HOME"] = str(home)
    sys.argv = ["podcast-bookmarks.py"]
    try:
        spec = importlib.util.spec_from_file_location("podcast_flow_under_test", FLOW_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def install_fake_defuddle(home, payload):
    bin_dir = home / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "defuddle"
    script.write_text(f"""#!/usr/bin/env python3
import json
print(json.dumps({payload!r}, ensure_ascii=False))
""", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bin_dir


class PodcastFlowTest(unittest.TestCase):
    def test_defuddle_long_webpage_resolves_as_webpage_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_path = os.environ.get("PATH", "")
            bin_dir = install_fake_defuddle(home, {
                "title": "Interview",
                "author": "Ada",
                "published": "2026-07-06",
                "markdown": "中文访谈内容。" * 80,
            })
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
            try:
                flow = import_flow(home)
                flow.MIN_TRANSCRIPT_CHARS = 20
                got = flow.resolve_article(
                    {"url": "https://example.test/interview", "title": "Old"},
                    str(home / "work"),
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(got["transcriptSource"], "webpage_transcript")
            self.assertEqual(got["transcriptProvider"], "defuddle")
            self.assertEqual(got["sourceReliability"], "edited")
            self.assertEqual(got["title"], "Interview")

    def test_short_webpage_with_youtube_embed_uses_youtube_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_path = os.environ.get("PATH", "")
            bin_dir = install_fake_defuddle(home, {
                "markdown": "short",
                "html": '<iframe src="https://www.youtube.com/embed/abc123"></iframe>',
            })
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
            try:
                flow = import_flow(home)
                flow.MIN_TRANSCRIPT_CHARS = 2000
                flow.resolve_youtube_transcript = lambda url, _workdir: {
                    "text": "caption text",
                    "transcriptSource": "youtube_unknown_caption",
                    "transcriptProvider": "firecrawl_youtube",
                    "captionKind": "unknown",
                    "sourceReliability": "unknown_caption",
                    "captionLanguage": "en",
                    "mediaSource": url,
                }
                got = flow.resolve_article({"url": "https://example.test/post"}, str(home / "work"))
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(got["mediaSource"], "https://www.youtube.com/watch?v=abc123")
            self.assertEqual(got["transcriptSource"], "youtube_unknown_caption")

    def test_short_webpage_without_media_fails_no_existing_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_path = os.environ.get("PATH", "")
            bin_dir = install_fake_defuddle(home, {"markdown": "short"})
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
            try:
                flow = import_flow(home)
                flow.MIN_TRANSCRIPT_CHARS = 2000
                flow.fetch_raw_html = lambda _url: ""
                with self.assertRaises(flow.ResolutionError) as ctx:
                    flow.resolve_article({"url": "https://example.test/post"}, str(home / "work"))
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(ctx.exception.code, "no-existing-transcript")

    def test_firecrawl_transcript_extraction_and_blocked_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            flow.MIN_TRANSCRIPT_CHARS = 10
            self.assertEqual(
                flow.extract_firecrawl_transcript("# Title\n\n## Transcript\n\nhello world"),
                "hello world",
            )
            self.assertEqual(
                flow.extract_firecrawl_transcript("403 Forbidden\n\n## Transcript\n\nhello world"),
                "",
            )

    def test_json3_vtt_and_language_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            flow = import_flow(home)
            json3 = home / "x.en.json3"
            json3.write_text(json.dumps({
                "events": [
                    {"segs": [{"utf8": "Hello"}, {"utf8": " world"}]},
                    {"segs": [{"utf8": "Hello world"}]},
                    {"segs": [{"utf8": "Next line"}]},
                ],
            }), encoding="utf-8")
            vtt = home / "x.zh.vtt"
            vtt.write_text("WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\n你好\n你好\n", encoding="utf-8")

            self.assertEqual(flow.parse_json3(json3), "Hello world\nNext line")
            self.assertEqual(flow.parse_vtt(vtt), "你好")
            self.assertEqual(flow.detect_language("这是中文" * 50), "zh")
            self.assertEqual(flow.detect_language("これは日本語です"), "en")
            self.assertEqual(flow.detect_language("hello", "en"), "en")


if __name__ == "__main__":
    unittest.main()
