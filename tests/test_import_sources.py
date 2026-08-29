import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.import_sources import extract_launcher


class ImportTests(unittest.TestCase):
    def test_cli_can_run_directly(self):
        result = subprocess.run(
            [sys.executable, "tools/import_sources.py", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_excludes_gitlink_and_github_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                for name, body in (
                    ("repo/app/build.gradle", b"android {}"),
                    ("repo/UserLAndLibrary", b"gitlink"),
                    ("repo/.github/workflows/build.yml", b"workflow"),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    output.addfile(info, io.BytesIO(body))
            destination = Path(directory) / "app"

            extract_launcher(archive, destination)

            self.assertTrue((destination / "app/build.gradle").is_file())
            self.assertFalse((destination / "UserLAndLibrary").exists())
            self.assertFalse((destination / ".github").exists())

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("repo/../../escape")
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))

            with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                extract_launcher(archive, Path(directory) / "app")


if __name__ == "__main__":
    unittest.main()
