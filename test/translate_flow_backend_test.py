import importlib.util
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "flows" / "translate-claude-api.py"


def import_flow(home):
    old_home = os.environ.get("INFO_COLLECTOR_HOME")
    old_argv = sys.argv[:]
    os.environ["INFO_COLLECTOR_HOME"] = str(home)
    sys.argv = ["translate-flow.py"]
    try:
        spec = importlib.util.spec_from_file_location("translate_flow_under_test", FLOW_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv
        if old_home is None:
            os.environ.pop("INFO_COLLECTOR_HOME", None)
        else:
            os.environ["INFO_COLLECTOR_HOME"] = old_home


class MockDeepSeekHandler(BaseHTTPRequestHandler):
    api_requests = []

    def do_GET(self):
        self.send_error(500, "DeepSeek backend test should use defuddle, not builtin fetch")

    def do_POST(self):
        if self.path != "/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        MockDeepSeekHandler.api_requests.append({
            "path": self.path,
            "authorization": self.headers.get("authorization"),
            "payload": payload,
        })
        body = json.dumps({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": (
                        "---\n"
                        "title: 后端 DeepSeek 测试\n"
                        "source: http://example.test/article\n"
                        "published: \n"
                        "date: 2026-07-05T12:00\n"
                        "authors: \n"
                        "---\n\n"
                        "# 后端 DeepSeek 测试（Backend DeepSeek Test）\n\n"
                        "这是一篇由 mock DeepSeek 返回的译文。"
                    ),
                },
            }],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class TranslateFlowBackendTest(unittest.TestCase):
    def setUp(self):
        MockDeepSeekHandler.api_requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockDeepSeekHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def install_fake_defuddle(self, home):
        bin_dir = home / "bin"
        bin_dir.mkdir()
        marker = home / "defuddle-called.json"
        implementation = bin_dir / "fake_defuddle.py"
        implementation.write_text(f"""#!/usr/bin/env python3
import json
import pathlib
import sys

pathlib.Path({str(marker)!r}).write_text(json.dumps(sys.argv), encoding="utf-8")
print(json.dumps({{
    "title": "Backend DeepSeek Test",
    "published": "2026-07-04",
    "author": "@fallback",
    "schemaOrgData": [{{"@type": "SocialMediaPosting", "author": {{"name": "Ada Lovelace"}}}}],
    "markdown": "# Backend DeepSeek Test\\n\\n"
                "This article text came from fake defuddle and is intentionally long enough.\\n\\n"
                "It proves the backend DeepSeek flow uses defuddle before calling the API.\\n\\n"
                "The translator should preserve URLs and return Markdown with frontmatter."
}}))
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
        return bin_dir, marker

    def test_deepseek_flow_runs_from_backend_spool_to_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir, defuddle_marker = self.install_fake_defuddle(home)
            old_path = os.environ.get("PATH", "")
            old_disable_defuddle = os.environ.pop("INFO_COLLECTOR_DISABLE_DEFUDDLE", None)
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
            flow = import_flow(home)
            spool = home / ".info-collector"
            (spool / "outbox").mkdir(parents=True)
            (spool / "state").mkdir(parents=True)
            out_dir = home / "translated"
            (spool / "config.json").write_text(json.dumps({
                "provider": "deepseek",
                "apiKey": "sk-test000000000000000000000",
                "baseUrl": self.base_url,
                "model": "deepseek-v4-flash",
                "outputDir": str(out_dir),
            }), encoding="utf-8")
            (spool / "outbox" / "translate.json").write_text(json.dumps({
                "processingType": "translate",
                "articles": [{
                    "articleKey": "article-1",
                    "url": "https://example.test/article",
                    "title": "Backend DeepSeek Test",
                }],
            }), encoding="utf-8")

            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    flow.main()
            finally:
                os.environ["PATH"] = old_path
                if old_disable_defuddle is not None:
                    os.environ["INFO_COLLECTOR_DISABLE_DEFUDDLE"] = old_disable_defuddle

            self.assertEqual(len(MockDeepSeekHandler.api_requests), 1)
            self.assertTrue(defuddle_marker.exists())
            defuddle_argv = json.loads(defuddle_marker.read_text(encoding="utf-8"))
            self.assertEqual(defuddle_argv[1:], ["parse", "https://example.test/article", "--json"])
            req = MockDeepSeekHandler.api_requests[0]
            self.assertEqual(req["authorization"], "Bearer sk-test000000000000000000000")
            self.assertEqual(req["payload"]["model"], "deepseek-v4-flash")
            self.assertEqual(req["payload"]["thinking"], {"type": "disabled"})
            self.assertIn("原文提取文本", req["payload"]["messages"][1]["content"])
            self.assertIn("正文提取器: defuddle", req["payload"]["messages"][1]["content"])
            self.assertIn("Ada Lovelace", req["payload"]["messages"][1]["content"])

            saved = list(out_dir.glob("*.md"))
            self.assertEqual(len(saved), 1)
            self.assertIn("# 后端 DeepSeek 测试", saved[0].read_text(encoding="utf-8"))

            reports = [
                json.loads(p.read_text(encoding="utf-8"))
                for p in (spool / "inbox").glob("translate-*.json")
            ]
            final_reports = [
                r for r in reports
                if any(item.get("status") == "done" for item in r.get("results", []))
            ]
            self.assertEqual(len(final_reports), 1)
            self.assertEqual(final_reports[0]["results"][0]["meta"]["savedTo"], str(saved[0]))


if __name__ == "__main__":
    unittest.main()
