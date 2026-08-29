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


if __name__ == "__main__":
    unittest.main()
