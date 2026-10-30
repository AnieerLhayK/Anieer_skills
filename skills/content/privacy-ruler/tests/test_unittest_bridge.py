"""Run the public CLI suite when a portable-package host uses unittest discovery."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

# Pytest already collects test_cli.py directly; avoid executing it twice there.
__test__ = False


class PortableBehaviorSuite(unittest.TestCase):
    def test_public_cli_behavior_suite(self):
        codex_data = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        staging = Path(os.environ.get("AI_TOOL_STAGING_DIR", str(codex_data / "cache" / "staging")))
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="privacy-ruler-unittest-", dir=staging) as temporary:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(Path(__file__).with_name("test_cli.py")),
                 "-q", "--basetemp", str(Path(temporary) / "pytest")],
                capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
