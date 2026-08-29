import unittest
from pathlib import Path


class ReadmeContractTests(unittest.TestCase):
    def test_readme_records_the_verified_r2_release_and_runtime_evidence(self):
        text = Path("README.md").read_text(encoding="utf-8")

        for required in (
            "2026.08.29-r2",
            "All ten apps passed",
            "v2026.08.29-r2",
            "actions/runs/33255923668",
            "actions/runs/33255923710",
            "UserLAnd-Assets-Support v1.5.1",
            "POST_NOTIFICATIONS",
            "MANAGE_EXTERNAL_STORAGE",
            "Andacious",
            "RECORD_AUDIO",
            "first-run downloads",
            "7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde",
        ):
            self.assertIn(required, text)
        self.assertNotIn("Pending r2 verification", text)
        self.assertNotIn("JDK 11 for FoxBox", text)


if __name__ == "__main__":
    unittest.main()
