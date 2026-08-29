import unittest
from pathlib import Path


class WorkflowContractTests(unittest.TestCase):
    def test_all_build_paths_use_locked_r2_metadata_and_java_17(self):
        for name in ("ci.yml", "upgrade-smoke.yml", "release.yml"):
            text = Path(".github/workflows", name).read_text()
            self.assertIn("release.lock.json", text, name)
            self.assertIn("java-version: '17'", text, name)
            self.assertNotIn("GITHUB_RUN_ID / 10000", text, name)
            self.assertNotIn("GITHUB_RUN_NUMBER", text, name)
            self.assertNotIn("matrix.app == 'foxbox'", text, name)
            self.assertIn("tools/stage_support_assets.py", text, name)

    def test_r2_release_requires_ten_runtime_evidence_bundles(self):
        text = Path(".github/workflows/upgrade-smoke.yml").read_text()

        for required in (
            "needs: upgrade-smoke",
            "v2026.08.29-r2",
            "*-upgrade-evidence",
            "pid-stability.txt",
            "ui.xml",
            "permissions.txt",
            "screenshot.png",
            "--sources-lock sources.lock.json",
            "--dependencies-lock dependencies.lock.json",
            "--release-lock release.lock.json",
            "Tag verified commit and publish r2",
            "gh release create",
        ):
            self.assertIn(required, text)
        self.assertNotIn("--prerelease", text)

    def test_manual_rebuild_cannot_bypass_runtime_release_gate(self):
        text = Path(".github/workflows/release.yml").read_text()

        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("tags:", text)
        self.assertNotIn("gh release create", text)
        self.assertNotIn("contents: write", text)

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

    def test_upgrade_smoke_uses_published_rc1_and_one_locked_r2_build(self):
        smoke = Path(".github/workflows/upgrade-smoke.yml").read_text()

        for required in (
            "push:",
            "branches:",
            "- main",
            "${{ matrix.app }}-verified-apk",
            "needs: upgrade-smoke",
            "Build and release all UserLAnd launcher APKs",
            "v2026.08.29-rc1",
            "gh release download",
            "SHA256SUMS",
            "release.lock.json",
            'scripts/build_app.sh "${{ matrix.app }}"',
            "steps.meta.outputs.version_name",
            "Set up Java 17 for emulator tools",
            "Enable KVM acceleration",
            "github.event_name == 'workflow_dispatch'",
        ):
            self.assertIn(required, smoke)

        self.assertLess(
            smoke.index("Build signed r2 APK"),
            smoke.index("Set up Java 17 for emulator tools"),
        )
        self.assertLess(
            smoke.index("Set up Java 17 for emulator tools"),
            smoke.index("Enable KVM acceleration"),
        )
        self.assertLess(
            smoke.index("Enable KVM acceleration"),
            smoke.index("Run emulator install launch and upgrade check"),
        )

        release_prefix = "Build and release all UserLAnd launcher APKs"
        self.assertEqual(2, smoke.count(release_prefix))
        self.assertIn("sudo chmod 0666 /dev/kvm", smoke)
        self.assertIn("test -w /dev/kvm", smoke)
        self.assertNotIn("Build signed upgrade pair", smoke)
        self.assertNotIn("GITHUB_RUN_ID / 10000", smoke)
        self.assertNotIn("matrix.app == 'foxbox'", smoke)

    def test_android_build_tools_are_exported_for_apk_verification(self):
        export = (
            'echo "$ANDROID_SDK_ROOT/build-tools/35.0.0" '
            '>> "$GITHUB_PATH"'
        )
        expected_counts = {
            "ci.yml": 1,
            "release.yml": 1,
            "upgrade-smoke.yml": 2,
        }
        for name, count in expected_counts.items():
            text = Path(".github/workflows", name).read_text()
            self.assertEqual(count, text.count(export), name)


if __name__ == "__main__":
    unittest.main()
