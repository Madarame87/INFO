import importlib.util
import contextlib
import io
import json
import os
import stat
import subprocess
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
                        "summary: \"文章说明了为什么应以评估驱动的方式持续改进智能体记忆系统。\"\n"
                        "tags: [\"Agents\", \"模型评估\", \"Memory Systems\"]\n"
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

    def test_startup_logging_survives_cp1252_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = {
                **os.environ,
                "INFO_COLLECTOR_HOME": str(home),
                "PYTHONUTF8": "0",
                "PYTHONIOENCODING": "cp1252",
            }

            proc = subprocess.run(
                [sys.executable, str(FLOW_PATH), "--manual"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=10,
            )

            self.assertEqual(
                proc.returncode,
                0,
                proc.stderr.decode("cp1252", errors="replace"),
            )
            self.assertNotIn(b"UnicodeEncodeError", proc.stderr)
            log_path = home / ".info-collector" / "state" / "translate-flow.log"
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("开始巡检翻译队列（manual）", log_text)
            self.assertIn("❌", log_text)

    def test_enrichment_parser_normalizes_aliases_and_inserts_summary_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            markdown = (
                "---\n"
                "title: 测试\n"
                "summary: \"这是一段用于测试的摘要。\"\n"
                "tags: [\"AI\", \"人工智能\", \"Agents\", \"Memory Systems\"]\n"
                "---\n\n"
                "# 测试\n\n正文"
            )
            enrichment = flow.extract_enrichment(markdown)
            self.assertEqual(enrichment["summary"], "这是一段用于测试的摘要。")
            self.assertEqual(enrichment["tags"], ["人工智能", "智能体", "记忆系统"])
            enriched = flow.ensure_summary_section(markdown, enrichment["summary"])
            self.assertIn("## 摘要\n\n这是一段用于测试的摘要。", enriched)

    def test_normalizer_accepts_preface_and_markdown_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            wrapped = (
                "下面是整理后的内容：\r\n"
                "```markdown\r\n"
                "---\r\n"
                "title: 测试\r\n"
                "source: https://example.test/article\r\n"
                "summary: \"一段摘要。\"\r\n"
                "tags: [\"智能体\", \"模型评估\"]\r\n"
                "---\r\n\r\n"
                "# 测试\r\n\r\n正文\r\n"
                "```"
            )
            document = flow.normalize_markdown_document(wrapped)
            self.assertTrue(document.startswith("---\r\n"))
            self.assertFalse(document.endswith("```"))
            self.assertEqual(flow.extract_enrichment(document)["tags"], ["智能体", "模型评估"])

    def test_normalizer_preserves_article_code_fence_at_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            document = (
                "---\n"
                "title: 测试\n"
                "source: https://example.test/article\n"
                "summary: \"一段摘要。\"\n"
                "tags: [\"智能体\", \"模型评估\"]\n"
                "---\n\n"
                "# 测试\n\n```python\nprint('ok')\n```"
            )
            self.assertTrue(flow.normalize_markdown_document(document).endswith("```"))

    def test_normalizer_inserts_missing_closing_frontmatter_delimiter(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            malformed = (
                "---\n"
                "title: 理解是新的瓶颈\n"
                "source: https://example.test/article\n"
                "published: 2026-07-02\n"
                "summary: \"一段完整摘要。\"\n"
                "tags: [\"智能体\", \"产品\"]\n"
                "## 摘要\n\n"
                "一段完整摘要。\n\n"
                "# 正文\n\n完整译文"
            )
            document = flow.normalize_markdown_document(malformed)
            self.assertIn('tags: ["智能体", "产品"]\n---\n\n## 摘要', document)
            self.assertEqual(flow.extract_enrichment(document)["tags"], ["智能体", "产品"])

            def unexpected_repair(*_args):
                raise AssertionError("本地可修复的分隔符问题不应调用 API")

            flow.repair_markdown_output = unexpected_repair
            with contextlib.redirect_stdout(io.StringIO()):
                prepared, enrichment = flow.prepare_enriched_markdown(
                    malformed,
                    "https://example.test/article",
                    "Understanding",
                    {"provider": "deepseek"},
                )
            self.assertIn("---\n\n## 摘要", prepared)
            self.assertEqual(enrichment["summary"], "一段完整摘要。")

    def test_prepare_repairs_missing_frontmatter_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            repaired = (
                "---\n"
                "title: 修复测试\n"
                "source: https://example.test/article\n"
                "summary: \"修复后生成的文章摘要。\"\n"
                "tags: [\"智能体\", \"模型评估\"]\n"
                "---\n\n"
                "# 修复测试\n\n完整译文"
            )
            calls = []

            def fake_repair(markdown, url, title, cfg):
                calls.append((markdown, url, title, cfg))
                return repaired

            flow.repair_markdown_output = fake_repair
            with contextlib.redirect_stdout(io.StringIO()):
                document, enrichment = flow.prepare_enriched_markdown(
                    "# 没有 frontmatter 的译文",
                    "https://example.test/article",
                    "Repair Test",
                    {"provider": "deepseek"},
                )
            self.assertEqual(len(calls), 1)
            self.assertTrue(document.startswith("---\n"))
            self.assertIn("## 摘要", document)
            self.assertEqual(enrichment["tags"], ["智能体", "模型评估"])

    def test_prepare_reports_safe_preview_when_single_repair_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            calls = []

            def bad_repair(*args):
                calls.append(args)
                return "仍然没有 frontmatter"

            flow.repair_markdown_output = bad_repair
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(RuntimeError, "模型输出格式修复失败"):
                    flow.prepare_enriched_markdown(
                        "原始译文但没有 frontmatter",
                        "https://example.test/article",
                        "Broken",
                        {"provider": "deepseek"},
                    )
            self.assertEqual(len(calls), 1)
            self.assertIn("原始输出安全预览：原始译文但没有 frontmatter", output.getvalue())
            self.assertIn("格式修复输出安全预览：仍然没有 frontmatter", output.getvalue())

    def test_deepseek_format_repair_uses_one_bounded_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = import_flow(Path(tmp))
            cfg = {
                "provider": "deepseek",
                "apiKey": "sk-test000000000000000000000",
                "baseUrl": self.base_url,
                "model": "deepseek-v4-flash",
            }
            repaired = flow.repair_markdown_output(
                "# 已有中文译文",
                "https://example.test/article",
                "Repair Test",
                cfg,
            )
            self.assertIn("summary:", repaired)
            self.assertEqual(len(MockDeepSeekHandler.api_requests), 1)
            request = MockDeepSeekHandler.api_requests[0]["payload"]
            self.assertEqual(request["temperature"], 0)
            self.assertEqual(request["thinking"], {"type": "disabled"})
            self.assertIn("Markdown 格式修复器", request["messages"][0]["content"])

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
            self.assertIn("summary 和 tags", req["payload"]["messages"][1]["content"])

            saved = list(out_dir.glob("*.md"))
            self.assertEqual(len(saved), 1)
            saved_text = saved[0].read_text(encoding="utf-8")
            self.assertIn("## 摘要", saved_text)
            self.assertIn("# 后端 DeepSeek 测试", saved_text)

            reports = [
                json.loads(p.read_text(encoding="utf-8"))
                for p in (spool / "inbox").glob("translate-*.json")
            ]
            final_reports = [
                r for r in reports
                if any(item.get("status") == "done" for item in r.get("results", []))
            ]
            self.assertEqual(len(final_reports), 1)
            result_meta = final_reports[0]["results"][0]["meta"]
            self.assertEqual(result_meta["savedTo"], str(saved[0]))
            self.assertEqual(result_meta["title"], "后端 DeepSeek 测试")
            self.assertEqual(result_meta["summary"], "文章说明了为什么应以评估驱动的方式持续改进智能体记忆系统。")
            self.assertEqual(result_meta["tags"], ["智能体", "模型评估", "记忆系统"])


if __name__ == "__main__":
    unittest.main()
