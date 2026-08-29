import unittest
from pathlib import Path


class SigningContractTests(unittest.TestCase):
    def test_secret_values_are_not_logged(self):
        text = Path("scripts/prepare_signing.sh").read_text()
        self.assertNotIn("set -x", text)
        self.assertNotIn("echo $ANDROID_", text)

    def test_gradle_reads_environment_only(self):
        text = Path("build-logic/signing.gradle").read_text()
        for name in (
            "ANDROID_KEYSTORE_FILE",
            "ANDROID_KEYSTORE_PASSWORD",
            "ANDROID_KEY_ALIAS",
            "ANDROID_KEY_PASSWORD",
        ):
            self.assertIn(f'System.getenv("{name}")', text)


if __name__ == "__main__":
    unittest.main()
