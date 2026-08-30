import json
import tempfile
import unittest
from pathlib import Path

from tools.render_runtime_catalog import render_catalog, write_catalog


class RuntimeCatalogTests(unittest.TestCase):
    def _asset(self, repository: str, release: str, filename: str, seed: str) -> dict:
        return {
            "asset_id": 42,
            "filename": filename,
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{release}/{filename}"
            ),
            "size": 987,
            "sha256": seed * 64,
        }

    def _app(self, package_id: str, release: str, seed: str) -> dict:
        repository = "CypherpunkArmory/UserLAnd-Assets-Debian"
        abi = "arm64"
        return {
            "id": package_id.rsplit(".", 1)[-1],
            "package_id": package_id,
            "repository": repository,
            "release": release,
            "abis": {
                abi: {
                    "asset_list": ["assets.tar.gz", "rootfs.tar.gz"],
                    "assets.txt": self._asset(
                        repository, release, f"{abi}-assets.txt", seed
                    ),
                    "assets.tar.gz": self._asset(
                        repository, release, f"{abi}-assets.tar.gz", seed
                    ),
                    "rootfs.tar.gz": self._asset(
                        repository, release, f"{abi}-rootfs.tar.gz", seed
                    ),
                }
            },
        }

    def _lock(self) -> dict:
        return {
            "schema_version": 1,
            "generated_at_utc": "2026-08-29T12:00:00+00:00",
            "apps": [
                self._app("tech.ula.foxbox_pro", "v7.7.9", "b"),
                self._app("tech.ula.andacious", "v7.8.11", "a"),
            ],
        }

    def test_runtime_projection_is_sorted_and_lossless(self):
        rendered = render_catalog(self._lock())

        self.assertEqual(
            ["tech.ula.andacious", "tech.ula.foxbox_pro"],
            [item["package_id"] for item in rendered["apps"]],
        )
        andacious = rendered["apps"][0]
        arm64 = andacious["abis"]["arm64"]
        self.assertEqual("v7.8.11", arm64["assets.tar.gz"]["release"])
        self.assertEqual("a" * 64, arm64["assets.tar.gz"]["sha256"])
        self.assertEqual(987, arm64["assets.tar.gz"]["size"])
        self.assertEqual(
            ["assets.tar.gz", "rootfs.tar.gz"], arm64["asset_list"]
        )
        self.assertNotIn("asset_id", arm64["assets.tar.gz"])
        self.assertNotIn("assets.txt", arm64)

    def test_catalog_writer_is_deterministic_and_check_detects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "r3-payloads.json"

            write_catalog(self._lock(), output)
            first = output.read_bytes()
            write_catalog(self._lock(), output, check=True)

            self.assertTrue(first.endswith(b"\n"))
            self.assertEqual(
                json.dumps(
                    json.loads(first), indent=2, sort_keys=True
                ).encode("utf-8")
                + b"\n",
                first,
            )
            output.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "runtime catalog differs"):
                write_catalog(self._lock(), output, check=True)


if __name__ == "__main__":
    unittest.main()
