import tempfile
import unittest
from pathlib import Path

from info_collector_platform import acquire_lock, lock_is_held, release_lock


class PlatformCompatTest(unittest.TestCase):
    def test_lock_conflict_probe_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "translate.lock"
            first = acquire_lock(path)
            self.assertIsNotNone(first)
            try:
                self.assertTrue(lock_is_held(path))
                self.assertIsNone(acquire_lock(path))
            finally:
                release_lock(first)

            self.assertFalse(lock_is_held(path))
            second = acquire_lock(path)
            self.assertIsNotNone(second)
            release_lock(second)


if __name__ == "__main__":
    unittest.main()

