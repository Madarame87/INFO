import importlib.util
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
            os.environ["INFO_COLLECTOR_HOME"] = str(home)
            os.environ["APPDATA"] = str(home / "AppData" / "Roaming")
            os.environ["PATH"] = os.pathsep.join(["C:\\Windows\\System32"] if os.name == "nt" else ["/usr/bin", "/bin"])
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

            path_parts = env["PATH"].split(os.pathsep)
            self.assertIn(str(node_bin), path_parts)
            self.assertLess(path_parts.index(str(node_bin)), len(path_parts))
            self.assertEqual(env["HOME"], str(home))

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
                flows = {
                    "translate": {
                        "command": [
                            sys.executable,
                            "-c",
                            f"from pathlib import Path; Path({str(marker)!r}).write_text('ok', encoding='utf-8')",
                        ],
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


if __name__ == "__main__":
    unittest.main()
