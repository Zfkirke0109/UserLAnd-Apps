import unittest
from pathlib import Path


class WorkflowContractTests(unittest.TestCase):
    def test_ci_contains_all_apps_and_no_secret_echo(self):
        text = Path(".github/workflows/ci.yml").read_text()
        for app in (
            "foxbox",
            "andacious",
            "gnuplot",
            "r",
            "libredocs",
            "devstudio",
            "inkscape",
            "birdbox",
            "gimp",
            "idle",
        ):
            self.assertIn(f"- {app}", text)
        self.assertNotIn("set -x", text)
        for secret in (
            "ANDROID_KEYSTORE_BASE64",
            "ANDROID_KEYSTORE_PASSWORD",
            "ANDROID_KEY_ALIAS",
            "ANDROID_KEY_PASSWORD",
        ):
            self.assertIn(f"secrets.{secret}", text)

    def test_verified_upgrade_bootstraps_one_release_with_monotonic_versions(self):
        smoke = Path(".github/workflows/upgrade-smoke.yml").read_text()
        release = Path(".github/workflows/release.yml").read_text()

        for required in (
            "push:",
            "branches:",
            "- main",
            "${{ matrix.app }}-verified-apk",
            "needs: upgrade-smoke",
            "Build and release all UserLAnd launcher APKs",
            "v2026.08.29-rc1",
            "gh release create",
            "--prerelease",
        ):
            self.assertIn(required, smoke)

        for workflow in (smoke, release):
            self.assertIn("GITHUB_RUN_ID / 10000", workflow)

    def test_android_build_tools_are_exported_for_apk_verification(self):
        export = (
            'echo "$ANDROID_SDK_ROOT/build-tools/35.0.0" '
            '>> "$GITHUB_PATH"'
        )
        expected_counts = {
            "ci.yml": 1,
            "release.yml": 2,
            "upgrade-smoke.yml": 2,
        }
        for name, count in expected_counts.items():
            text = Path(".github/workflows", name).read_text()
            self.assertEqual(count, text.count(export), name)


if __name__ == "__main__":
    unittest.main()
