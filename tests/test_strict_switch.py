"""The CCD_STRICT switch must stop a green suite from hiding the pinned defects.

A default run keeps ``tests/test_known_issues.py`` green because the four regressions are
wrapped in ``unittest.expectedFailure``. That is deliberate, but it means "74 tests OK"
says the pipeline is intact, not that the look is correct. With ``CCD_STRICT=1`` the same
four tests run unprotected and fail, so an unfixed defect cannot be reported as success.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "tests/test_known_issues.py"


def _run_known_issues(strict: bool) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("CCD_STRICT", None)
    if strict:
        env["CCD_STRICT"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, TARGET, "-q"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


class StrictSwitchTests(unittest.TestCase):
    def test_default_run_reports_the_four_defects_as_expected_failures(self) -> None:
        result = _run_known_issues(strict=False)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
        self.assertIn("expected failures=4", result.stderr)

    def test_strict_run_turns_the_same_four_into_hard_failures(self) -> None:
        result = _run_known_issues(strict=True)
        self.assertNotEqual(result.returncode, 0, msg="CCD_STRICT=1 must not report success")
        self.assertNotIn("expected failures", result.stderr)
        self.assertIn("failures=4", result.stderr)


if __name__ == "__main__":
    unittest.main()
