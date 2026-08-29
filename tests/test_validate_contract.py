import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.validate_contract import validate_contract


class ContractCliTests(unittest.TestCase):
    def test_repository_contract_is_complete(self):
        result = subprocess.run(
            [sys.executable, "tools/validate_contract.py"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("Contract valid: 10 apps\n", result.stdout)


class ContractTests(unittest.TestCase):
    def test_duplicate_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = json.loads(Path("sources.lock.json").read_text())
            source["apps"][1]["package_id"] = source["apps"][0]["package_id"]
            (root / "sources.lock.json").write_text(json.dumps(source))
            (root / "dependencies.lock.json").write_text(
                Path("dependencies.lock.json").read_text()
            )

            errors = validate_contract(root)

            self.assertIn("duplicate package_id: tech.ula.foxbox_pro", errors)


if __name__ == "__main__":
    unittest.main()
