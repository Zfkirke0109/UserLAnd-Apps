import tempfile
import unittest
from pathlib import Path

from tools.release_manifest import sha256_file, write_checksums


class ReleaseManifestTests(unittest.TestCase):
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
