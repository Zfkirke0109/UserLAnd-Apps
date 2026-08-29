import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPOSITORY_ROOT / "tools" / "assert_visible_window.py"


class VisibleWindowTests(unittest.TestCase):
    def run_checker(
        self, dumpsys: str, package_id: str = "com.android.permissioncontroller"
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dumpsys_path = Path(temporary_directory) / "window.txt"
            dumpsys_path.write_text(dumpsys)
            return subprocess.run(
                ["python3", str(CHECKER), str(dumpsys_path), package_id],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_android_15_visible_activity_is_detected_without_focus_fields(self):
        result = self.run_checker(
            """WINDOW MANAGER WINDOWS (dumpsys window windows)
  Window #7 Window{ee250b5 u0 com.android.permissioncontroller/com.android.permissioncontroller.permission.ui.GrantPermissionsActivity}:
    mActivityRecord=ActivityRecord{8304851 u0 com.android.permissioncontroller/.permission.ui.GrantPermissionsActivity t8}
    mViewVisibility=0x0 mHaveFrame=true mObscured=false
    mHasSurface=true isReadyForDisplay()=true mWindowRemovalAllowed=false
"""
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_hidden_or_surface_less_activity_is_not_visible(self):
        result = self.run_checker(
            """WINDOW MANAGER WINDOWS (dumpsys window windows)
  Window #7 Window{ee250b5 u0 com.android.permissioncontroller/.GrantPermissionsActivity}:
    mViewVisibility=0x8 mHaveFrame=true mObscured=false
    mHasSurface=false isReadyForDisplay()=false mWindowRemovalAllowed=false
"""
        )

        self.assertNotEqual(0, result.returncode)

    def test_other_visible_package_does_not_satisfy_target(self):
        result = self.run_checker(
            """WINDOW MANAGER WINDOWS (dumpsys window windows)
  Window #1 Window{abc u0 tech.ula.foxbox_pro/tech.ula.library.MainActivity}:
    mViewVisibility=0x0 mHaveFrame=true mObscured=false
    mHasSurface=true isReadyForDisplay()=true mWindowRemovalAllowed=false
"""
        )

        self.assertNotEqual(0, result.returncode)

    def test_visible_android_settings_activity_is_detected(self):
        result = self.run_checker(
            """WINDOW MANAGER WINDOWS (dumpsys window windows)
  Window #3 Window{def u0 com.android.settings/.Settings$ManageExternalStorageDetailsActivity}:
    mViewVisibility=0x0 mHaveFrame=true mObscured=false
    mHasSurface=true isReadyForDisplay()=true mWindowRemovalAllowed=false
""",
            "com.android.settings",
        )

        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
