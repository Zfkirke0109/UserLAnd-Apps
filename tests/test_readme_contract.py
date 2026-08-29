import unittest
from pathlib import Path


class ReadmeContractTests(unittest.TestCase):
    def test_readme_describes_r2_without_claiming_unrun_verification(self):
        text = Path("README.md").read_text(encoding="utf-8")

        for required in (
            "2026.08.29-r2",
            "Pending r2 verification",
            "UserLAnd-Assets-Support v1.5.1",
            "POST_NOTIFICATIONS",
            "MANAGE_EXTERNAL_STORAGE",
            "Andacious",
            "RECORD_AUDIO",
            "first-run downloads",
            "7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde",
        ):
            self.assertIn(required, text)
        self.assertNotIn("All ten apps passed", text)
        self.assertNotIn("JDK 11 for FoxBox", text)


if __name__ == "__main__":
    unittest.main()
