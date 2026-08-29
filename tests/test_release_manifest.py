import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_manifest import build_manifest, sha256_file, write_checksums


class ReleaseManifestTests(unittest.TestCase):
    def _fixture(self, directory: str, metadata_overrides: dict | None = None):
        dist = Path(directory)
        sources = json.loads(Path("sources.lock.json").read_text())
        release = json.loads(Path("release.lock.json").read_text())
        for app in sources["apps"]:
            (dist / app["output_name"]).write_bytes(app["id"].encode())

        packages = {
            app["output_name"]: app["package_id"] for app in sources["apps"]
        }
        overrides = metadata_overrides or {}

        def metadata(apk: Path) -> dict:
            return {
                "package_id": packages[apk.name],
                "version_code": release["version_code"],
                "version_name": release["version_name"],
                "min_sdk": 21,
                "target_sdk": 35,
                "certificate_sha256": (
                    "82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:"
                    "9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC"
                ),
                **overrides,
            }

        return dist, sources, release, metadata

    def test_manifest_records_exact_r3_and_shared_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            dist, _sources, _release, metadata = self._fixture(directory)

            with patch("tools.release_manifest.inspect_apk", side_effect=metadata):
                try:
                    manifest = build_manifest(
                        dist,
                        Path("sources.lock.json"),
                        Path("dependencies.lock.json"),
                        Path("release.lock.json"),
                        "2026-08-29T12:00:00+00:00",
                    )
                except TypeError as error:
                    self.fail(f"r3 manifest interface is missing: {error}")

            self.assertEqual(2, manifest["schema_version"])
            self.assertEqual("v2026.08.29-r3", manifest["release_tag"])
            self.assertEqual("2026.08.29-r3", manifest["version_name"])
            self.assertEqual(2003329001, manifest["version_code"])
            self.assertEqual(
                {
                    "repository": "Lily-Rader/UserLAndLibrary",
                    "ref": "8751d21debb0f336b2437106db46bc708e81b7d3",
                },
                manifest["shared_dependency"],
            )
            self.assertEqual("v1.5.1", manifest["support_assets"]["release"])
            self.assertEqual(4, len(manifest["support_assets"]["archives"]))
            self.assertEqual(10, len(manifest["apps"]))
            self.assertTrue(
                all(app["version_name"].endswith("r3") for app in manifest["apps"])
            )

    def test_manifest_rejects_apk_version_that_differs_from_release_lock(self):
        for field, value in (
            ("version_code", 2003328999),
            ("version_name", "2026.08.29-not-r3"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                dist, _sources, _release, metadata = self._fixture(
                    directory, {field: value}
                )
                with patch("tools.release_manifest.inspect_apk", side_effect=metadata):
                    with self.assertRaisesRegex(ValueError, f"{field} mismatch"):
                        build_manifest(
                            dist,
                            Path("sources.lock.json"),
                            Path("dependencies.lock.json"),
                            Path("release.lock.json"),
                            "2026-08-29T12:00:00+00:00",
                        )

    def test_checksums_are_sorted_and_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "B.apk").write_bytes(b"b")
            (root / "A.apk").write_bytes(b"a")
            output = root / "SHA256SUMS"

            write_checksums(root, output)

            lines = output.read_text().splitlines()
            self.assertTrue(lines[0].endswith("  A.apk"))
            self.assertTrue(lines[1].endswith("  B.apk"))
            self.assertEqual(64, len(lines[0].split()[0]))
            self.assertEqual(sha256_file(root / "A.apk"), lines[0].split()[0])


if __name__ == "__main__":
    unittest.main()
