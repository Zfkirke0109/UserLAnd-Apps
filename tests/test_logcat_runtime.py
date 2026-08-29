import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPOSITORY_ROOT / "tools" / "assert_no_app_crash.py"
PACKAGE_ID = "tech.ula.foxbox_pro"


class LogcatRuntimeTests(unittest.TestCase):
    def run_checker(self, logcat: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logcat_path = Path(temporary_directory) / "logcat.txt"
            logcat_path.write_text(logcat)
            return subprocess.run(
                ["python3", str(CHECKER), PACKAGE_ID, str(logcat_path)],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_normal_uiautomator_androidruntime_lines_do_not_implicate_app(self):
        result = self.run_checker(
            """08-29 13:00:52 I ActivityManager: Start proc 2269:tech.ula.foxbox_pro/u0a148
08-29 13:00:59 D AndroidRuntime: >>>>>> START com.android.internal.os.RuntimeInit uid 2000 <<<<<<
08-29 13:00:59 D AndroidRuntime: Calling main entry com.android.commands.uiautomator.Launcher
08-29 13:01:00 D AndroidRuntime: Shutting down VM
"""
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_target_fatal_exception_is_rejected(self):
        result = self.run_checker(
            """08-29 13:00:55 E AndroidRuntime: FATAL EXCEPTION: main
08-29 13:00:55 E AndroidRuntime: Process: tech.ula.foxbox_pro, PID: 2269
08-29 13:00:55 E AndroidRuntime: java.lang.IllegalStateException: broken
"""
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("fatal exception", result.stderr.lower())

    def test_other_package_fatal_does_not_implicate_target(self):
        result = self.run_checker(
            """08-29 13:00:52 I ActivityManager: Start proc 2269:tech.ula.foxbox_pro/u0a148
08-29 13:00:55 E AndroidRuntime: FATAL EXCEPTION: main
08-29 13:00:55 E AndroidRuntime: Process: com.example.other, PID: 1000
08-29 13:00:55 E AndroidRuntime: java.lang.IllegalStateException: broken
"""
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_target_anr_is_rejected(self):
        result = self.run_checker(
            "08-29 13:01:00 E ActivityManager: ANR in tech.ula.foxbox_pro\n"
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("anr", result.stderr.lower())

    def test_target_force_finish_is_rejected(self):
        result = self.run_checker(
            "08-29 13:01:00 W ActivityTaskManager: Force finishing activity tech.ula.foxbox_pro/.MainActivity\n"
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("force-finish", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
