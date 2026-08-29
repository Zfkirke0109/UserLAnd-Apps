import tempfile
import unittest
from pathlib import Path

from tools.verify_dependency_tree import (
    REQUIRED_FILES,
    SUPPORT_ABIS,
    SUPPORT_FILES,
    verify_dependency_tree,
)


class DependencyTreeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
