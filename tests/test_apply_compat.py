import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from tools.apply_compat import apply_profile, load_profile


class CompatibilityTests(unittest.TestCase):
    def test_check_mode_preserves_dangling_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "build.gradle").write_text("mavenCentral()\n")
            (workspace / ".env").symlink_to("missing-env")
            profile = root / "profile.json"
            profile.write_text(
                '{"operations": [{"type": "assert_absent", '
                '"path": "build.gradle", "text": "jcenter()"}]}'
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "tools/apply_compat.py",
                    "--root",
                    str(workspace),
                    "--profile",
                    str(profile),
                    "--check",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)

    def test_profile_can_extend_shared_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shared.json").write_text(
                '{"operations": [{"type": "assert_absent", '
                '"path": "build.gradle", "text": "jcenter()"}]}'
            )
            (root / "app.json").write_text(
                '{"extends": "shared.json", "operations": []}'
            )

            profile = load_profile(root / "app.json")

            self.assertEqual(1, len(profile["operations"]))

    def test_replace_requires_exact_anchor_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build.gradle").write_text("jcenter()\njcenter()\n")
            profile = {
                "operations": [
                    {
                        "type": "replace",
                        "path": "build.gradle",
                        "old": "jcenter()",
                        "new": "mavenCentral()",
                        "count": 1,
                    }
                ]
            }

            with self.assertRaisesRegex(
                ValueError, "expected 1 anchors, found 2"
            ):
                apply_profile(root, profile)

    def test_replace_is_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build.gradle").write_text("jcenter()\n")
            profile = {
                "operations": [
                    {
                        "type": "replace",
                        "path": "build.gradle",
                        "old": "jcenter()",
                        "new": "mavenCentral()",
                        "count": 1,
                    }
                ]
            }

            self.assertEqual(["build.gradle"], apply_profile(root, profile))
            self.assertEqual(
                "mavenCentral()\n", (root / "build.gradle").read_text()
            )


if __name__ == "__main__":
    unittest.main()
