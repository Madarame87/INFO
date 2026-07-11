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
    old_home = os.environ.get("INFO_COLLECTOR_HOME")
    old_argv = sys.argv[:]
    os.environ["INFO_COLLECTOR_HOME"] = str(home)
    sys.argv = ["podcast-bookmarks.py"]
    try:
        spec = importlib.util.spec_from_file_location("podcast_flow_under_test", FLOW_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv
        if old_home is None:
            os.environ.pop("INFO_COLLECTOR_HOME", None)
        else:
            os.environ["INFO_COLLECTOR_HOME"] = old_home


def install_fake_defuddle(home, payload):
    bin_dir = home / "bin"
    bin_dir.mkdir(exist_ok=True)
    implementation = bin_dir / "fake_defuddle.py"
    implementation.write_text(f"""#!/usr/bin/env python3
import json
print(json.dumps({payload!r}))
""", encoding="utf-8")
    if os.name == "nt":
        script = bin_dir / "defuddle.cmd"
        script.write_text(
            f'@echo off\r\n"{sys.executable}" "{implementation}" %*\r\n',
            encoding="utf-8",
        )
    else:
        script = bin_dir / "defuddle"
        script.write_text(implementation.read_text(encoding="utf-8"), encoding="utf-8")
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

    def test_youtube_metadata_is_written_to_workdir_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            flow = import_flow(home)
            flow.WORK_ROOT = str(home / "work")
            flow.firecrawl_transcript = lambda _url: {
                "text": "caption " * 400,
                "transcriptSource": "youtube_unknown_caption",
                "transcriptProvider": "firecrawl_youtube",
                "captionKind": "unknown",
                "sourceReliability": "unknown_caption",
                "captionLanguage": "en",
                "mediaSource": "https://www.youtube.com/watch?v=abc123",
            }
            flow.yt_dlp_transcript = lambda _url, _workdir: None
            flow.fetch_youtube_metadata = lambda _url: {
                "title": "Video Title",
                "channel": "Sequoia Capital",
                "channelUrl": "https://www.youtube.com/@sequoiacapital",
                "published": "2026-06-16",
            }

            resolved = flow.resolve_youtube_transcript("https://youtu.be/abc123", str(home / "tmp"))
            workdir, _meta = flow.prepare_workdir({
                "articleKey": "https://www.youtube.com/watch?v=abc123",
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "Bookmark Title",
            }, resolved)
            meta = json.loads((Path(workdir) / "meta.json").read_text(encoding="utf-8"))

            self.assertEqual(meta["title"], "Video Title")
            self.assertEqual(meta["channel"], "Sequoia Capital")
            self.assertEqual(meta["channelUrl"], "https://www.youtube.com/@sequoiacapital")
            self.assertEqual(meta["published"], "2026-06-16")

    def test_youtube_publish_date_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))

            self.assertEqual(
                flow.parse_youtube_publish_date(
                    '"publishDate":{"simpleText":"Jun 16, 2026"}'
                ),
                "2026-06-16",
            )
            self.assertEqual(
                flow.parse_youtube_publish_date(
                    '"uploadDate":"2026-06-16T10:30:00-07:00"'
                ),
                "2026-06-16",
            )
            self.assertEqual(flow.parse_youtube_publish_date('"publishedTimeText":"12 days ago"'), "")

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
