import unittest
from pathlib import Path


class PayloadLockWorkflowTests(unittest.TestCase):
    def test_workflow_runs_exact_ten_by_four_matrix_and_retains_records(self):
        path = Path(".github/workflows/payload-lock.yml")
        self.assertTrue(path.is_file(), "payload-lock workflow must exist")
        text = path.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", text)
        for app_id in (
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
            self.assertEqual(1, text.count(f"          - {app_id}\n"))
        for abi in ("arm64", "arm", "x86", "x86_64"):
            self.assertEqual(1, text.count(f"          - {abi}\n"))
        self.assertIn("tools/payload_lock.py record", text)
        self.assertIn("tools/payload_lock.py aggregate", text)
        self.assertIn("tools/payload_lock.py verify", text)
        self.assertIn("tools/render_runtime_catalog.py", text)
        self.assertIn("payload-record-${{ matrix.app }}-${{ matrix.abi }}", text)
        self.assertIn("payload-lock-r3", text)


if __name__ == "__main__":
    unittest.main()
