import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import tools.verify_dependency_tree as verifier
from tools.verify_dependency_tree import (
    REQUIRED_FILES,
    SUPPORT_ABIS,
    SUPPORT_FILES,
    verify_dependency_tree,
)


class DependencyTreeTests(unittest.TestCase):
    SUPPORT_SHA256 = {
        "arm64-v8a": "ec9bb2e652afb0ceab2cc6830809214ee4d786d31ef8463d0ec213aca67ff9ce",
        "armeabi-v7a": "af0a2667dbf90076fbc4bdde40538db84950bc596aabe24261a766ae57ccfe41",
        "x86": "9cb71e2e79fa0d1eb453cf669c8232e0000878a190f5c01f3f17cd01c06ca4d0",
        "x86_64": "897e0902202c6c07cb4efd9b0f00f5c33d5d2925092c62b3c14951ba7a371252",
    }

    def _complete_tree(self, root: Path) -> None:
        for relative in REQUIRED_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        for abi in SUPPORT_ABIS:
            jni = root / f"UserLAndLibrary/app/src/main/jniLibs/{abi}"
            jni.mkdir(parents=True, exist_ok=True)
            for filename in SUPPORT_FILES:
                body = abi if filename == "lib_arch.so" else "fixture"
                (jni / filename).write_text(body, encoding="utf-8")
            marker = root / f"UserLAndLibrary/app/src/main/.support-assets/{abi}.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps(
                    {
                        "abi": abi,
                        "archive_sha256": self.SUPPORT_SHA256[abi],
                        "release": "v1.5.1",
                        "staged_files": sorted(path.name for path in jni.iterdir()),
                    }
                ),
                encoding="utf-8",
            )

    def test_dependency_restorer_stages_locked_support_archives(self):
        text = Path("scripts/prepare_dependencies.sh").read_text()

        self.assertIn("support_assets", text)
        self.assertIn("tools/stage_support_assets.py", text)
        self.assertIn("unzip -t", text)
        self.assertIn("SUPPORT_SHA256", text)

    def test_missing_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = verify_dependency_tree(Path(directory))

            self.assertTrue(
                any("UserLAndLibrary/app/build.gradle" in error for error in errors)
            )

    def test_support_assets_are_required_for_every_abi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")

            errors = verify_dependency_tree(root)

            for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64"):
                self.assertTrue(any(abi in error for error in errors), errors)

    def test_runtime_architecture_marker_is_required_for_every_abi(self):
        self.assertIn("lib_arch.so", SUPPORT_FILES)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            for abi in SUPPORT_ABIS:
                jni = root / f"UserLAndLibrary/app/src/main/jniLibs/{abi}"
                jni.mkdir(parents=True, exist_ok=True)
                for filename in SUPPORT_FILES:
                    if filename != "lib_arch.so":
                        (jni / filename).write_text("fixture", encoding="utf-8")
                marker = (
                    root
                    / f"UserLAndLibrary/app/src/main/.support-assets/{abi}.json"
                )
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text('{"release": "v1.5.1"}', encoding="utf-8")

            errors = verify_dependency_tree(root)

            for abi in SUPPORT_ABIS:
                expected = f"{abi}/lib_arch.so"
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_v151_requires_static_busybox_companion_and_extraction_scripts(self):
        for name in (
            "lib_busybox_static.so",
            "lib_libbusybox.so.1.37.0.so",
            "lib_extractFilesystem.sh.so",
            "lib_addNonRootUser.sh.so",
        ):
            self.assertIn(name, SUPPORT_FILES)

    def test_marker_file_list_must_equal_staged_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._complete_tree(root)
            unexpected = (
                root
                / "UserLAndLibrary/app/src/main/jniLibs/arm64-v8a/lib_unrecorded.so"
            )
            unexpected.write_text("unexpected", encoding="utf-8")

            errors = verify_dependency_tree(root)

            self.assertTrue(
                any("marker file list mismatch for arm64-v8a" in error for error in errors),
                errors,
            )

    def test_marker_abi_and_archive_digest_must_match_lock(self):
        cases = (
            ("abi", "x86"),
            ("archive_sha256", "0" * 64),
        )
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._complete_tree(root)
                marker = (
                    root
                    / "UserLAndLibrary/app/src/main/.support-assets/arm64-v8a.json"
                )
                payload = json.loads(marker.read_text(encoding="utf-8"))
                payload[field] = value
                marker.write_text(json.dumps(payload), encoding="utf-8")

                errors = verify_dependency_tree(root)

                self.assertTrue(
                    any(f"invalid support marker for arm64-v8a" in error for error in errors),
                    errors,
                )

    def test_elf_needed_and_missing_companion_are_reported(self):
        fixture = """
          0x0000000000000001 (NEEDED) Shared library: [libbusybox.so.1.37.0]
          0x0000000000000001 (NEEDED) Shared library: [libc.so]
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "busybox"
            path.write_bytes(b"\x7fELFfixture")
            completed = subprocess.CompletedProcess(
                args=["readelf"], returncode=0, stdout=fixture, stderr=""
            )
            with patch("tools.verify_dependency_tree.subprocess.run", return_value=completed):
                needed = verifier.elf_needed(path)

        self.assertEqual(("libbusybox.so.1.37.0", "libc.so"), needed)
        self.assertEqual(
            ("libbusybox.so.1.37.0",),
            verifier.missing_needed_libraries(needed, set()),
        )

    def test_elf_dependency_may_be_supplied_by_another_packaged_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._complete_tree(root)
            busybox = (
                root
                / "UserLAndLibrary/app/src/main/jniLibs/arm64-v8a/lib_busybox.so"
            )
            busybox.write_bytes(b"\x7fELFfixture")
            remote_lib = (
                root
                / "UserLAndLibrary/remote-desktop-clients/remoteClientLib/"
                "src/main/jniLibs/arm64-v8a/libc++_shared.so"
            )
            remote_lib.parent.mkdir(parents=True, exist_ok=True)
            remote_lib.write_text("fixture", encoding="utf-8")

            with patch(
                "tools.verify_dependency_tree.elf_needed",
                return_value=("libc++_shared.so",),
            ):
                errors = verify_dependency_tree(root)

            self.assertFalse(
                any("libc++_shared.so" in error for error in errors),
                errors,
            )


if __name__ == "__main__":
    unittest.main()
