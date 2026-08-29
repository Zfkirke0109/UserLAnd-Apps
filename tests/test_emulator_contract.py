import unittest
from pathlib import Path


class EmulatorContractTests(unittest.TestCase):
    def test_smoke_script_is_executable(self):
        mode = Path("scripts/emulator_smoke.sh").stat().st_mode
        self.assertNotEqual(0, mode & 0o111)

    def test_smoke_script_upgrades_before_a_sustained_cold_launch(self):
        text = Path("scripts/emulator_smoke.sh").read_text()
        self.assertIn('adb install "$OLD_APK"', text)
        self.assertIn('adb install -r "$NEW_APK"', text)
        self.assertIn('adb shell am force-stop "$PACKAGE_ID"', text)
        self.assertIn("adb shell am start -W", text)
        self.assertIn('adb shell pidof -s "$PACKAGE_ID"', text)
        self.assertIn("dumpsys activity activities", text)
        self.assertIn("for stable_second in $(seq 1 20)", text)
        self.assertLess(
            text.index('adb install -r "$NEW_APK"'),
            text.index('adb shell am force-stop "$PACKAGE_ID"'),
        )
        self.assertLess(
            text.index('adb shell am force-stop "$PACKAGE_ID"'),
            text.index("adb shell am start -W"),
        )
        self.assertNotIn("adb shell monkey", text)

    def test_smoke_script_fails_on_crash_dead_process_or_wrong_ui(self):
        text = Path("scripts/emulator_smoke.sh").read_text()

        for required in (
            "assert_no_app_crash",
            "process died during stability window",
            "tech.ula.library.MainActivity",
            "adb logcat -b crash -d",
            "FATAL EXCEPTION",
            "AndroidRuntime",
            "ANR in",
            "Force finishing activity",
            "uiautomator dump",
            "ui.xml",
            "screenshot.png",
        ):
            self.assertIn(required, text)

    def test_smoke_script_verifies_r2_metadata_certificate_and_permissions(self):
        text = Path("scripts/emulator_smoke.sh").read_text()

        for required in (
            "EXPECTED_VERSION_NAME",
            "2026.08.29-r2",
            "apksigner verify --verbose --print-certs",
            "82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC",
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.MANAGE_EXTERNAL_STORAGE",
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
            "android.permission.RECORD_AUDIO",
            "android.permission.CAMERA",
            "MANAGE_EXTERNAL_STORAGE deny",
            "MANAGE_EXTERNAL_STORAGE allow",
            "mCurrentFocus.*com\\.android\\.settings",
            "mCurrentFocus.*permissioncontroller",
        ):
            self.assertIn(required, text)

    def test_exit_trap_always_captures_runtime_evidence(self):
        text = Path("scripts/emulator_smoke.sh").read_text()

        self.assertIn("trap capture_evidence EXIT", text)
        for filename in (
            "logcat.txt",
            "crash-buffer.txt",
            "activity.txt",
            "window.txt",
            "final-package.txt",
            "appops.txt",
            "permissions.txt",
        ):
            self.assertIn(filename, text)


if __name__ == "__main__":
    unittest.main()
