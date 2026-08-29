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
    EXPECTED_SUPPORT_ASSETS = {
        "arm64-v8a": "ec9bb2e652afb0ceab2cc6830809214ee4d786d31ef8463d0ec213aca67ff9ce",
        "armeabi-v7a": "af0a2667dbf90076fbc4bdde40538db84950bc596aabe24261a766ae57ccfe41",
        "x86": "9cb71e2e79fa0d1eb453cf669c8232e0000878a190f5c01f3f17cd01c06ca4d0",
        "x86_64": "897e0902202c6c07cb4efd9b0f00f5c33d5d2925092c62b3c14951ba7a371252",
    }

    def _copy_contract(self, root: Path) -> None:
        for name in (
            "sources.lock.json",
            "dependencies.lock.json",
            "release.lock.json",
        ):
            (root / name).write_text(Path(name).read_text(encoding="utf-8"))

    def test_r3_release_contract_is_exact_and_monotonic(self):
        release_path = Path("release.lock.json")
        self.assertTrue(release_path.is_file(), "release.lock.json must exist")
        release = json.loads(release_path.read_text(encoding="utf-8"))

        self.assertEqual("v2026.08.29-r3", release["release_tag"])
        self.assertEqual("2026.08.29-r3", release["version_name"])
        self.assertEqual(2003329001, release["version_code"])
        self.assertEqual("v2026.08.29-r2", release["upgrade_from_tag"])
        self.assertEqual(2003329000, release["upgrade_from_version_code"])
        self.assertGreater(
            release["version_code"], release["upgrade_from_version_code"]
        )
        self.assertEqual([], validate_contract(Path(".")))

    def test_wrong_release_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("sources.lock.json", "dependencies.lock.json"):
                (root / name).write_text(Path(name).read_text(encoding="utf-8"))
            release = {
                "schema_version": 1,
                "release_tag": "v2026.08.29-r3",
                "version_name": "2026.08.29-rc2",
                "version_code": 2003329001,
                "upgrade_from_tag": "v2026.08.29-r2",
                "upgrade_from_version_code": 2003329000,
            }
            (root / "release.lock.json").write_text(json.dumps(release))

            self.assertIn(
                "release version_name must be 2026.08.29-r3",
                validate_contract(root),
            )

    def test_foxbox_uses_current_upstream_commit(self):
        sources = json.loads(Path("sources.lock.json").read_text())
        foxbox = next(app for app in sources["apps"] if app["id"] == "foxbox")

        self.assertEqual(
            "7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde",
            foxbox["source_ref"],
        )

    def test_support_assets_are_exactly_locked_to_v1_5_1(self):
        dependencies = json.loads(Path("dependencies.lock.json").read_text())
        self.assertIn("support_assets", dependencies)
        support = dependencies["support_assets"]

        self.assertEqual("CypherpunkArmory/UserLAnd-Assets-Support", support["repository"])
        self.assertEqual("v1.5.1", support["release"])
        self.assertEqual(
            self.EXPECTED_SUPPORT_ASSETS,
            {item["abi"]: item["sha256"] for item in support["archives"]},
        )
        for item in support["archives"]:
            self.assertEqual(f"{item['abi']}-assets.zip", item["filename"])
            self.assertEqual(
                "https://github.com/CypherpunkArmory/UserLAnd-Assets-Support/"
                f"releases/download/v1.5.1/{item['filename']}",
                item["url"],
            )

    def test_duplicate_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = json.loads(Path("sources.lock.json").read_text())
            source["apps"][1]["package_id"] = source["apps"][0]["package_id"]
            (root / "sources.lock.json").write_text(json.dumps(source))
            (root / "dependencies.lock.json").write_text(
                Path("dependencies.lock.json").read_text()
            )
            if Path("release.lock.json").is_file():
                (root / "release.lock.json").write_text(
                    Path("release.lock.json").read_text()
                )

            errors = validate_contract(root)

            self.assertIn("duplicate package_id: tech.ula.foxbox_pro", errors)


if __name__ == "__main__":
    unittest.main()
