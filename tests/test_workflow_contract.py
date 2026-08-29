import unittest
from pathlib import Path


class WorkflowContractTests(unittest.TestCase):
    def test_ci_contains_all_apps_and_no_secret_echo(self):
        text = Path(".github/workflows/ci.yml").read_text()
        for app in (
            "foxbox",
            "andacious",
            "gnuplot",
            "r",
            "libredocs",
            "devstudio",
            "inkscape",
            "birdbox",
            "gimp",
            "idle",
        ):
            self.assertIn(f"- {app}", text)
        self.assertNotIn("set -x", text)
        for secret in (
            "ANDROID_KEYSTORE_BASE64",
            "ANDROID_KEYSTORE_PASSWORD",
            "ANDROID_KEY_ALIAS",
            "ANDROID_KEY_PASSWORD",
        ):
            self.assertIn(f"secrets.{secret}", text)


if __name__ == "__main__":
    unittest.main()
