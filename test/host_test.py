import importlib.util
import os
import tempfile
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
            node_bin = home / ".nvm" / "versions" / "node" / "v99.0.0" / "bin"
            node_bin.mkdir(parents=True)
            (node_bin / "pi").write_text("#!/bin/sh\n", encoding="utf-8")

            old_home = os.environ.get("HOME")
            old_path = os.environ.get("PATH")
            os.environ["HOME"] = str(home)
            os.environ["PATH"] = "/usr/bin:/bin"
            try:
                host = import_host()
                env = host.trigger_env()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_path is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = old_path

            path_parts = env["PATH"].split(os.pathsep)
            self.assertIn(str(node_bin), path_parts)
            self.assertLess(path_parts.index(str(node_bin)), path_parts.index("/usr/bin"))
            self.assertEqual(env["HOME"], str(home))


if __name__ == "__main__":
    unittest.main()
