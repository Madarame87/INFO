import importlib.util
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST_PATH = ROOT / "host" / "info_collector_host.py"


def import_host():
    spec = importlib.util.spec_from_file_location("info_collector_host_under_test", HOST_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InfoCollectorHostTest(unittest.TestCase):
    def test_open_output_only_opens_registered_generated_file_under_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_home = os.environ.get("INFO_COLLECTOR_HOME")
            os.environ["INFO_COLLECTOR_HOME"] = str(home)
            try:
                host = import_host()
                state = home / ".info-collector" / "state"
                output = home / "Documents" / "InfoCollector" / "周报" / "本周回顾.md"
                state.mkdir(parents=True)
                output.parent.mkdir(parents=True)
                output.write_text("# 本周回顾\n", encoding="utf-8")
                (state / "weekly-report-status.json").write_text(json.dumps({
                    "latestReport": str(output),
                }), encoding="utf-8")
                opened = []
                host.open_local_path = lambda path: opened.append(path)
                result = host.handle_open_output({"processingType": "weekly-report"})
                self.assertTrue(result["ok"])
                self.assertEqual(opened, [output.resolve()])

                outside = home.parent / "outside-report.md"
                outside.write_text("blocked", encoding="utf-8")
                (state / "weekly-report-status.json").write_text(json.dumps({
                    "latestReport": str(outside),
                }), encoding="utf-8")
                denied = host.handle_open_output({"processingType": "weekly-report"})
                self.assertFalse(denied["ok"])
                self.assertIn("用户目录", denied["error"])
                outside.unlink()
            finally:
                if old_home is None:
                    os.environ.pop("INFO_COLLECTOR_HOME", None)
                else:
                    os.environ["INFO_COLLECTOR_HOME"] = old_home

    def test_trigger_env_adds_user_node_bins(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            if os.name == "nt":
                node_bin = home / "AppData" / "Roaming" / "npm"
            else:
                node_bin = home / ".nvm" / "versions" / "node" / "v99.0.0" / "bin"
            node_bin.mkdir(parents=True)
            (node_bin / "pi").write_text("#!/bin/sh\n", encoding="utf-8")

            old_home = os.environ.get("INFO_COLLECTOR_HOME")
            old_path = os.environ.get("PATH")
            old_appdata = os.environ.get("APPDATA")
            old_python_utf8 = os.environ.get("PYTHONUTF8")
            old_python_io_encoding = os.environ.get("PYTHONIOENCODING")
            os.environ["INFO_COLLECTOR_HOME"] = str(home)
            os.environ["APPDATA"] = str(home / "AppData" / "Roaming")
            os.environ["PATH"] = os.pathsep.join(["C:\\Windows\\System32"] if os.name == "nt" else ["/usr/bin", "/bin"])
            os.environ["PYTHONUTF8"] = "0"
            os.environ["PYTHONIOENCODING"] = "cp1252"
            try:
                host = import_host()
                env = host.trigger_env()
            finally:
                if old_home is None:
                    os.environ.pop("INFO_COLLECTOR_HOME", None)
                else:
                    os.environ["INFO_COLLECTOR_HOME"] = old_home
                if old_path is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = old_path
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata
                if old_python_utf8 is None:
                    os.environ.pop("PYTHONUTF8", None)
                else:
                    os.environ["PYTHONUTF8"] = old_python_utf8
                if old_python_io_encoding is None:
                    os.environ.pop("PYTHONIOENCODING", None)
                else:
                    os.environ["PYTHONIOENCODING"] = old_python_io_encoding

            path_parts = env["PATH"].split(os.pathsep)
            self.assertIn(str(node_bin), path_parts)
            self.assertLess(path_parts.index(str(node_bin)), len(path_parts))
            # Windows CI may expose the same temp directory through its long
            # path in one place and an 8.3 alias (RUNNER~1) in another.
            self.assertTrue(Path(env["HOME"]).samefile(home))
            self.assertEqual(env["PYTHONUTF8"], "1")
            self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_native_messaging_ping_uses_binary_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "INFO_COLLECTOR_HOME": tmp}
            proc = subprocess.Popen(
                [sys.executable, str(HOST_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            payload = json.dumps({"type": "ping"}).encode("utf-8")
            stdout, stderr = proc.communicate(struct.pack("<I", len(payload)) + payload, timeout=10)
            self.assertEqual(proc.returncode, 0, stderr.decode("utf-8", errors="replace"))
            self.assertGreaterEqual(len(stdout), 4)
            (length,) = struct.unpack("<I", stdout[:4])
            self.assertEqual(json.loads(stdout[4:4 + length].decode("utf-8")), {"ok": True, "pong": True})

    def test_sync_writes_outbox_and_trigger_starts_registered_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_home = os.environ.get("INFO_COLLECTOR_HOME")
            os.environ["INFO_COLLECTOR_HOME"] = str(home)
            try:
                host = import_host()
                response = host.handle_sync({
                    "generatedAt": "2026-07-11T12:00:00Z",
                    "outbox": {
                        "translate": [{
                            "articleKey": "https://example.test/a",
                            "url": "https://example.test/a",
                            "title": "A",
                        }],
                    },
                    "acks": [],
                })
                self.assertTrue(response["ok"])
                outbox = json.loads((home / ".info-collector" / "outbox" / "translate.json").read_text(encoding="utf-8"))
                self.assertEqual(outbox["articles"][0]["title"], "A")

                marker = home / "triggered.txt"
                trusted_bin = home / ".info-collector" / "bin"
                trusted_bin.mkdir(parents=True)
                flow_script = trusted_bin / "test-flow.py"
                flow_script.write_text(
                    f"from pathlib import Path\nPath({str(marker)!r}).write_text('ok', encoding='utf-8')\n",
                    encoding="utf-8",
                )
                flows = {
                    "translate": {
                        "command": [
                            sys.executable,
                            str(flow_script),
                        ],
                        "scriptSha256": hashlib.sha256(flow_script.read_bytes()).hexdigest(),
                        "lockFile": str(home / ".info-collector" / "state" / "translate.lock"),
                        "intervalSeconds": None,
                    },
                }
                (home / ".info-collector" / "flows.json").write_text(json.dumps(flows), encoding="utf-8")
                triggered = host.handle_trigger({"processingType": "translate"})
                self.assertTrue(triggered["ok"])
                self.assertTrue(triggered["started"])
                for _ in range(50):
                    if marker.exists():
                        break
                    time.sleep(0.05)
                self.assertEqual(marker.read_text(encoding="utf-8"), "ok")
                for proc in host._TRIGGERED_PROCESSES:
                    proc.wait(timeout=5)
            finally:
                if old_home is None:
                    os.environ.pop("INFO_COLLECTOR_HOME", None)
                else:
                    os.environ["INFO_COLLECTOR_HOME"] = old_home

    def test_user_capture_is_bounded_and_enriches_matching_outbox_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_home = os.environ.get("INFO_COLLECTOR_HOME")
            os.environ["INFO_COLLECTOR_HOME"] = str(home)
            try:
                host = import_host()
                article_key = "https://example.test/private-article"
                result = host.handle_capture({
                    "articleKey": article_key,
                    "url": article_key,
                    "capturedAt": "2026-08-10T12:00:00Z",
                    "capture": {
                        "title": "Visible article",
                        "content": "Visible paragraph with verified article content. " * 12,
                    },
                })
                self.assertTrue(result["ok"])
                capture_path = Path(result["captureFile"])
                self.assertTrue(capture_path.is_file())
                stored = json.loads(capture_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["extractor"], "browser-rendered-user-initiated")
                self.assertNotIn("cookies", stored)

                host.handle_sync({
                    "generatedAt": "2026-08-10T12:01:00Z",
                    "outbox": {"translate": [{
                        "articleKey": article_key,
                        "url": article_key,
                        "title": "Visible article",
                    }]},
                    "acks": [],
                })
                outbox = json.loads((home / ".info-collector" / "outbox" / "translate.json").read_text(encoding="utf-8"))
                self.assertEqual(outbox["articles"][0]["captureFile"], str(capture_path))

                rejected = host.handle_capture({
                    "articleKey": article_key,
                    "url": article_key,
                    "capture": {"content": "too short"},
                })
                self.assertFalse(rejected["ok"])
            finally:
                if old_home is None:
                    os.environ.pop("INFO_COLLECTOR_HOME", None)
                else:
                    os.environ["INFO_COLLECTOR_HOME"] = old_home

    def test_trigger_rejects_untrusted_or_modified_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old_home = os.environ.get("INFO_COLLECTOR_HOME")
            os.environ["INFO_COLLECTOR_HOME"] = str(home)
            try:
                host = import_host()
                outside = home / "outside.py"
                outside.write_text("print('no')", encoding="utf-8")
                (home / ".info-collector").mkdir(parents=True, exist_ok=True)
                (home / ".info-collector" / "flows.json").write_text(json.dumps({
                    "translate": {
                        "command": [sys.executable, str(outside)],
                        "scriptSha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
                        "lockFile": str(home / ".info-collector" / "state" / "translate.lock"),
                    },
                }), encoding="utf-8")
                denied = host.handle_trigger({"processingType": "translate"})
                self.assertFalse(denied["ok"])
                self.assertIn("受信任", denied["error"])
            finally:
                if old_home is None:
                    os.environ.pop("INFO_COLLECTOR_HOME", None)
                else:
                    os.environ["INFO_COLLECTOR_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
