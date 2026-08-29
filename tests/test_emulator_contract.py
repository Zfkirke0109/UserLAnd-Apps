import unittest
from pathlib import Path


class EmulatorContractTests(unittest.TestCase):
    def test_smoke_script_installs_launches_and_upgrades(self):
        text = Path("scripts/emulator_smoke.sh").read_text()
        self.assertIn('adb install "$OLD_APK"', text)
        self.assertIn("android.intent.category.LAUNCHER", text)
        self.assertIn('adb install -r "$NEW_APK"', text)
        self.assertIn("dumpsys package", text)


if __name__ == "__main__":
    unittest.main()
