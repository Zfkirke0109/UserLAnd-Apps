import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from tools.apply_compat import apply_profile, load_profile


class CompatibilityTests(unittest.TestCase):
    def test_modern_profiles_add_namespaces_without_affecting_foxbox(self):
        modern = load_profile(Path("profiles/andacious.json"))
        legacy = load_profile(Path("profiles/foxbox.json"))

        def has_bvnc_namespace(profile):
            return any(
                operation.get("path")
                == "UserLAndLibrary/remote-desktop-clients/bVNC/build.gradle"
                and "namespace" in operation.get("text", "")
                for operation in profile["operations"]
            )

        self.assertTrue(has_bvnc_namespace(modern))
        self.assertFalse(has_bvnc_namespace(legacy))

    def test_profiles_remove_retired_test_dependency_and_preserve_synthetics(self):
        modern = load_profile(Path("profiles/andacious.json"))
        legacy = load_profile(Path("profiles/foxbox.json"))

        self.assertTrue(
            any(
                "barista:3.1.0" in operation.get("old", "")
                and operation.get("new") == ""
                for operation in legacy["operations"]
            )
        )
        self.assertTrue(
            any(
                operation.get("path") == "build.gradle"
                and operation.get("old") == "kotlin_version = '1.9.20'"
                and operation.get("new") == "kotlin_version = '1.7.20'"
                for operation in modern["operations"]
            )
        )
        self.assertTrue(
            any(
                operation.get("old") == "xml.enabled = true"
                and operation.get("new") == "xml.required = true"
                for operation in modern["operations"]
            )
        )
        self.assertTrue(
            any(
                operation.get("path") == "UserLAndLibrary/app/build.gradle"
                and "buildConfig true" in operation.get("text", "")
                for operation in modern["operations"]
            )
        )

    def test_modern_profiles_restore_foxbox_scaling_defaults(self):
        modern = load_profile(Path("profiles/andacious.json"))
        legacy = load_profile(Path("profiles/foxbox.json"))

        def scaling_defaults(profile):
            return [
                operation
                for operation in profile["operations"]
                if operation.get("path") == "CustomLibrary/build.gradle"
                and "DEFAULT_PREF_CUSTOM_SCALING_ENABLED"
                in operation.get("text", "")
                and "default_pref_custom_scaling_enabled"
                in operation.get("text", "")
                and "DEFAULT_PREF_SCALING" in operation.get("text", "")
                and "default_pref_scaling" in operation.get("text", "")
            ]

        self.assertEqual(1, len(scaling_defaults(modern)))
        self.assertEqual([], scaling_defaults(legacy))

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
