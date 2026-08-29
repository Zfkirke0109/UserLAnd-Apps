import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.payload_lock import (
    PAYLOAD_SOURCES,
    aggregate_records,
    build_payload_record,
    verify_payload_lock,
)


ABIS = ("arm64", "arm", "x86", "x86_64")


class PayloadLockTests(unittest.TestCase):
    def _sources(self) -> dict:
        return {
            "schema_version": 1,
            "apps": [
                {
                    "id": "foxbox",
                    "package_id": "tech.ula.foxbox_pro",
                },
                {
                    "id": "andacious",
                    "package_id": "tech.ula.andacious",
                },
            ],
        }

    def _asset(self, repository: str, release: str, filename: str, seed: str) -> dict:
        return {
            "asset_id": 100,
            "filename": filename,
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{release}/{filename}"
            ),
            "size": 123,
            "sha256": seed * 64,
        }

    def _app(self, app_id: str, package_id: str, release: str, seed: str) -> dict:
        repository = "CypherpunkArmory/UserLAnd-Assets-Debian"
        abis = {}
        for abi in ABIS:
            abis[abi] = {
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
        return {
            "id": app_id,
            "package_id": package_id,
            "repository": repository,
            "release": release,
            "abis": abis,
        }

    def _lock(self) -> dict:
        return {
            "schema_version": 1,
            "generated_at_utc": "2026-08-29T12:00:00+00:00",
            "apps": [
                self._app("foxbox", "tech.ula.foxbox_pro", "v7.7.9", "a"),
                self._app("andacious", "tech.ula.andacious", "v7.8.11", "b"),
            ],
        }

    def _write_fixture(self, root: Path, lock: dict) -> tuple[Path, Path]:
        lock_path = root / "payloads.lock.json"
        sources_path = root / "sources.lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        sources_path.write_text(json.dumps(self._sources()), encoding="utf-8")
        return lock_path, sources_path

    def test_complete_lock_matches_exact_source_packages_and_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path, sources_path = self._write_fixture(
                Path(directory), self._lock()
            )

            self.assertEqual([], verify_payload_lock(lock_path, sources_path))

    def test_lock_rejects_latest_missing_digest_and_missing_abi(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = self._lock()
            lock["apps"][0]["release"] = "latest"
            lock["apps"][0]["abis"]["arm64"]["assets.tar.gz"]["sha256"] = ""
            del lock["apps"][0]["abis"]["x86"]
            lock_path, sources_path = self._write_fixture(Path(directory), lock)

            errors = "\n".join(verify_payload_lock(lock_path, sources_path))

            self.assertIn("mutable release selector", errors)
            self.assertIn("missing SHA-256", errors)
            self.assertIn("missing ABI x86", errors)

    def test_lock_rejects_duplicate_package_and_source_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = self._lock()
            lock["apps"][1]["package_id"] = "tech.ula.foxbox_pro"
            lock_path, sources_path = self._write_fixture(Path(directory), lock)

            errors = "\n".join(verify_payload_lock(lock_path, sources_path))

            self.assertIn("duplicate package_id: tech.ula.foxbox_pro", errors)
            self.assertIn("missing package_id: tech.ula.andacious", errors)

    def test_lock_rejects_wrong_asset_name_url_size_id_and_list(self):
        mutations = {
            "filename": "wrong.tar.gz",
            "url": "http://example.invalid/latest/file",
            "size": 0,
            "asset_id": 0,
        }
        for field, value in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                lock = self._lock()
                lock["apps"][0]["abis"]["arm64"]["rootfs.tar.gz"][field] = value
                lock_path, sources_path = self._write_fixture(Path(directory), lock)

                errors = "\n".join(verify_payload_lock(lock_path, sources_path))

                self.assertIn(field.replace("_", " "), errors)

        with tempfile.TemporaryDirectory() as directory:
            lock = self._lock()
            lock["apps"][0]["abis"]["arm64"]["asset_list"] = []
            lock_path, sources_path = self._write_fixture(Path(directory), lock)

            self.assertIn(
                "empty asset list",
                "\n".join(verify_payload_lock(lock_path, sources_path)),
            )

    def test_lock_rejects_unexpected_abi_or_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = self._lock()
            arm64 = lock["apps"][0]["abis"]["arm64"]
            arm64["extra.tar.gz"] = copy.deepcopy(arm64["assets.tar.gz"])
            lock["apps"][0]["abis"]["mips"] = copy.deepcopy(arm64)
            lock_path, sources_path = self._write_fixture(Path(directory), lock)

            errors = "\n".join(verify_payload_lock(lock_path, sources_path))

            self.assertIn("unexpected ABI mips", errors)
            self.assertIn("unexpected payload extra.tar.gz", errors)

    def test_asset_list_must_name_exact_two_runtime_payloads(self):
        cases = (
            ["assets.tar.gz"],
            ["assets.tar.gz", "rootfs.tar.gz", "unexpected.tar.gz"],
        )
        for asset_list in cases:
            with self.subTest(asset_list=asset_list), tempfile.TemporaryDirectory() as directory:
                lock = self._lock()
                lock["apps"][0]["abis"]["arm64"]["asset_list"] = asset_list
                lock_path, sources_path = self._write_fixture(Path(directory), lock)

                errors = "\n".join(verify_payload_lock(lock_path, sources_path))

                self.assertIn(
                    "asset list must contain assets.tar.gz and rootfs.tar.gz",
                    errors,
                )

    def test_lock_rejects_repository_or_release_outside_fixed_app_source(self):
        cases = (
            ("repository", "CypherpunkArmory/UserLAnd-Assets-Gnuplot"),
            ("release", "v99.99.99"),
        )
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                lock = self._lock()
                lock["apps"][0][field] = value
                lock_path, sources_path = self._write_fixture(Path(directory), lock)

                errors = "\n".join(verify_payload_lock(lock_path, sources_path))

                expected = PAYLOAD_SOURCES["foxbox"][field]
                self.assertIn(f"{field} must be {expected}", errors)

    def test_record_hashes_downloaded_bytes_and_parses_literal_asset_list(self):
        source = PAYLOAD_SOURCES["andacious"]
        abi = "arm64"
        bodies = {
            f"{abi}-assets.txt": (
                b"assets.txt ignored\nassets.tar.gz one\nrootfs.tar.gz two\n"
            ),
            f"{abi}-assets.tar.gz": b"assets archive bytes",
            f"{abi}-rootfs.tar.gz": b"rootfs archive bytes",
        }
        assets = []
        by_url = {}
        for index, (filename, body) in enumerate(bodies.items(), start=1):
            url = (
                f"https://github.com/{source['repository']}/releases/download/"
                f"{source['release']}/{filename}"
            )
            assets.append(
                {
                    "id": index,
                    "name": filename,
                    "size": len(body),
                    "browser_download_url": url,
                }
            )
            by_url[url] = body

        record = build_payload_record(
            "andacious",
            "tech.ula.andacious",
            abi,
            {"tag_name": source["release"], "assets": assets},
            lambda url: io.BytesIO(by_url[url]),
        )

        self.assertEqual(["assets.tar.gz", "rootfs.tar.gz"], record["asset_list"])
        self.assertEqual(
            hashlib.sha256(bodies[f"{abi}-assets.tar.gz"]).hexdigest(),
            record["assets.tar.gz"]["sha256"],
        )
        self.assertEqual(len(bodies[f"{abi}-rootfs.tar.gz"]), record["rootfs.tar.gz"]["size"])

    def test_record_rejects_wrong_tag_or_downloaded_size(self):
        source = PAYLOAD_SOURCES["foxbox"]
        with self.assertRaisesRegex(ValueError, "release tag mismatch"):
            build_payload_record(
                "foxbox",
                "tech.ula.foxbox_pro",
                "arm64",
                {"tag_name": "latest", "assets": []},
                lambda _url: io.BytesIO(),
            )

        filenames = (
            "arm64-assets.txt",
            "arm64-assets.tar.gz",
            "arm64-rootfs.tar.gz",
        )
        assets = []
        by_url = {}
        for index, filename in enumerate(filenames, start=1):
            url = (
                f"https://github.com/{source['repository']}/releases/download/"
                f"{source['release']}/{filename}"
            )
            body = b"assets.tar.gz x\nrootfs.tar.gz y\n" if filename.endswith(".txt") else b"x"
            assets.append(
                {
                    "id": index,
                    "name": filename,
                    "size": len(body) + (1 if filename.endswith("rootfs.tar.gz") else 0),
                    "browser_download_url": url,
                }
            )
            by_url[url] = body

        with self.assertRaisesRegex(ValueError, "downloaded size mismatch"):
            build_payload_record(
                "foxbox",
                "tech.ula.foxbox_pro",
                "arm64",
                {"tag_name": source["release"], "assets": assets},
                lambda url: io.BytesIO(by_url[url]),
            )

    def test_aggregate_requires_one_record_per_source_app_and_abi(self):
        sources = self._sources()
        records = []
        for app in sources["apps"]:
            source = PAYLOAD_SOURCES[app["id"]]
            for abi in ABIS:
                complete = self._app(
                    app["id"], app["package_id"], source["release"], "c"
                )
                complete["repository"] = source["repository"]
                record = {
                    "schema_version": 1,
                    "id": app["id"],
                    "package_id": app["package_id"],
                    "repository": source["repository"],
                    "release": source["release"],
                    "abi": abi,
                    **complete["abis"][abi],
                }
                for logical_name in ("assets.txt", "assets.tar.gz", "rootfs.tar.gz"):
                    filename = f"{abi}-{logical_name}"
                    record[logical_name]["filename"] = filename
                    record[logical_name]["url"] = (
                        f"https://github.com/{source['repository']}/releases/download/"
                        f"{source['release']}/{filename}"
                    )
                records.append(record)

        lock = aggregate_records(sources, records)

        self.assertEqual(
            ["tech.ula.andacious", "tech.ula.foxbox_pro"],
            [app["package_id"] for app in lock["apps"]],
        )
        self.assertEqual(set(ABIS), set(lock["apps"][0]["abis"]))
        with self.assertRaisesRegex(ValueError, "missing record"):
            aggregate_records(sources, records[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate record"):
            aggregate_records(sources, [*records, records[0]])


if __name__ == "__main__":
    unittest.main()
