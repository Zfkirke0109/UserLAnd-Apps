import hashlib
import importlib
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path


class SupportAssetStagingTests(unittest.TestCase):
    def setUp(self):
        self.tool = Path("tools/stage_support_assets.py")
        self.assertTrue(self.tool.is_file(), "support asset staging tool must exist")
        module = importlib.import_module("tools.stage_support_assets")
        self.stage_archive = module.stage_archive

    def _archive(self, root: Path, members: list[tuple[str, bytes]]) -> Path:
        archive = root / "assets.zip"
        with zipfile.ZipFile(archive, "w") as output:
            for name, body in members:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    output.writestr(name, body)
        return archive

    def test_flat_support_files_are_staged_with_android_library_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self._archive(
                root,
                [("proot", b"proot-data"), ("busybox", b"busybox-data"), ("assets.txt", b"list")],
            )
            destination = root / "jniLibs"

            staged = self.stage_archive(archive, destination, "arm64-v8a", "v1.5.1")

            self.assertEqual(
                [
                    "lib_arch.so",
                    "lib_assets.txt.so",
                    "lib_busybox.so",
                    "lib_proot.so",
                ],
                [path.name for path in staged],
            )
            self.assertEqual(
                "arm64-v8a",
                (destination / "arm64-v8a/lib_arch.so").read_text(),
            )
            self.assertEqual(
                b"proot-data",
                (destination / "arm64-v8a/lib_proot.so").read_bytes(),
            )
            marker = destination.parent / ".support-assets/arm64-v8a.json"
            self.assertIn(hashlib.sha256(archive.read_bytes()).hexdigest(), marker.read_text())
            self.assertIn('"release": "v1.5.1"', marker.read_text())

    def test_unsafe_or_nonflat_members_are_rejected_before_writing(self):
        cases = (
            [("../escape", b"x")],
            [("/absolute", b"x")],
            [("nested/proot", b"x")],
            [("proot", b"one"), ("proot", b"two")],
            [("arch", b"forged-marker")],
            [],
        )
        for members in cases:
            with self.subTest(members=[name for name, _ in members]):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    archive = self._archive(root, members)
                    destination = root / "jniLibs"
                    with self.assertRaises(ValueError):
                        self.stage_archive(
                            archive, destination, "arm64-v8a", "v1.5.1"
                        )
                    self.assertFalse((destination / "arm64-v8a").exists())

    def test_symbolic_link_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "assets.zip"
            info = zipfile.ZipInfo("proot")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr(info, "target")

            with self.assertRaises(ValueError):
                self.stage_archive(
                    archive, root / "jniLibs", "arm64-v8a", "v1.5.1"
                )

    def test_unloadable_optional_webrtc_echo_canceller_is_not_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self._archive(
                root,
                [
                    ("proot", b"proot-data"),
                    ("libwebrtc-util.so", b"missing-dependency"),
                    ("module-echo-cancel.so", b"depends-on-webrtc-util"),
                ],
            )
            destination = root / "jniLibs"

            staged = self.stage_archive(
                archive, destination, "arm64-v8a", "v1.5.1"
            )

            self.assertEqual(
                ["lib_arch.so", "lib_proot.so"],
                [path.name for path in staged],
            )
            marker = destination.parent / ".support-assets/arm64-v8a.json"
            self.assertNotIn("webrtc", marker.read_text(encoding="utf-8"))
            self.assertNotIn("echo-cancel", marker.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
