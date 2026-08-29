import unittest
from pathlib import Path


class BuildContractTests(unittest.TestCase):
    def test_build_is_isolated_and_release_only(self):
        text = Path("scripts/build_app.sh").read_text()
        self.assertIn("RUNNER_TEMP", text)
        self.assertIn("tools/apply_compat.py", text)
        self.assertIn(":app:assembleRelease", text)
        self.assertIn("ulaVersionCode", text)
        self.assertIn("ulaVersionName", text)

    def test_build_requires_restored_dependencies(self):
        text = Path("scripts/build_app.sh").read_text()
        self.assertIn("tools/verify_dependency_tree.py", text)
        self.assertIn("UserLAndLibrary", text)

    def test_build_defaults_to_locked_r3_version(self):
        text = Path("scripts/build_app.sh").read_text()

        self.assertIn("release.lock.json", text)
        self.assertIn("VERSION_CODE=$(read_release version_code)", text)
        self.assertIn("VERSION_NAME=$(read_release version_name)", text)
        self.assertIn("usage: $0 APP_ID [VERSION_CODE VERSION_NAME]", text)


if __name__ == "__main__":
    unittest.main()
