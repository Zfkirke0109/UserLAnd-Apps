import json
import re
import unittest
from fnmatch import fnmatch
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

    def test_release_gate_requires_twenty_runtime_evidence_bundles(self):
        text = Path(".github/workflows/upgrade-smoke.yml").read_text()

        for required in (
            "needs: upgrade-smoke",
            "pid-stability.txt",
            "ui.xml",
            "permissions.txt",
            "screenshot.png",
            "setup-complete.png",
            "download-journal.json",
            "payload-digest-report.txt",
            "--sources-lock sources.lock.json",
            "--dependencies-lock dependencies.lock.json",
            "--release-lock release.lock.json",
            "gh release create",
        ):
            self.assertIn(required, text)
        self.assertNotIn("--prerelease", text)

    def test_release_tag_and_upgrade_baseline_come_from_the_lock(self):
        """A hard-coded tag ships the previous release under the new name."""
        release = json.loads(Path("release.lock.json").read_text())
        text = Path(".github/workflows/upgrade-smoke.yml").read_text()

        # The workflow must derive both tags from release.lock.json rather
        # than carrying a literal that goes stale one release later.
        self.assertIn("release.lock.json", text)
        for stale in (
            "v2026.08.29-rc1",
            "publish r2",
            "Build signed r2 APK",
        ):
            self.assertNotIn(stale, text, f"stale release target: {stale}")

        # No literal tag may appear at all. Allowing the lock's own values
        # through is not enough: publishing under the previous release's tag
        # uses a literal the lock does contain, and is the exact defect this
        # guards against.
        self.assertEqual(
            set(re.findall(r"v2026\.\d{2}\.\d{2}-[a-z0-9]+", text)),
            set(),
            "release targets must be read from release.lock.json, not written out",
        )
        self.assertIn("RELEASE_TAG={release['release_tag']}", text)
        self.assertIn(
            "BASELINE_TAG: ${{ steps.meta.outputs.upgrade_from_tag }}", text
        )
        # Guard the lock itself: the two tags must differ, or the release
        # overwrites the build it was supposed to be an upgrade from.
        self.assertNotEqual(release["release_tag"], release["upgrade_from_tag"])

    @staticmethod
    def _artifact_names(text: str) -> tuple[list[str], list[str]]:
        """Collect upload names and download patterns from a workflow.

        Scanned line by line rather than parsed, so the tests keep working
        without adding a YAML dependency to the contract job.
        """
        uploads: list[str] = []
        downloads: list[str] = []
        action = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("uses:"):
                if "actions/upload-artifact" in stripped:
                    action = "upload"
                elif "actions/download-artifact" in stripped:
                    action = "download"
                else:
                    action = None
            if action == "upload" and stripped.startswith("name:"):
                uploads.append(stripped[len("name:"):].strip().strip("'\""))
                action = None
            elif action == "download" and stripped.startswith("pattern:"):
                downloads.append(stripped[len("pattern:"):].strip().strip("'\""))
                action = None
        return uploads, downloads

    def test_artifact_name_scan_finds_both_directions(self):
        """The scan below is only evidence if it really reads a workflow."""
        uploads, downloads = self._artifact_names(
            Path(".github/workflows/upgrade-smoke.yml").read_text()
        )
        self.assertEqual(len(uploads), 2)
        self.assertEqual(len(downloads), 2)

    def test_every_artifact_download_pattern_matches_an_upload(self):
        """A download pattern that matches nothing yields an empty gate."""
        for name in ("ci.yml", "upgrade-smoke.yml", "release.yml"):
            uploads, downloads = self._artifact_names(
                Path(".github/workflows", name).read_text()
            )

            # Expand the matrix placeholders an artifact name can carry, so a
            # pattern is checked against names that can really be produced.
            concrete = []
            for upload in uploads:
                expanded = re.sub(r"\$\{\{[^}]*api-level[^}]*\}\}", "35", upload)
                expanded = re.sub(r"\$\{\{[^}]*\}\}", "foxbox", expanded)
                concrete.append(expanded)

            for pattern in downloads:
                self.assertTrue(
                    any(fnmatch(upload, pattern) for upload in concrete),
                    f"{name}: pattern {pattern!r} matches no uploaded artifact "
                    f"among {concrete}",
                )

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

    def test_upgrade_smoke_uses_the_published_baseline_and_one_locked_build(self):
        smoke = Path(".github/workflows/upgrade-smoke.yml").read_text()

        for required in (
            "push:",
            "branches:",
            "- main",
            "${{ matrix.app }}-verified-apk",
            "needs: upgrade-smoke",
            "Build and release all UserLAnd launcher APKs",
            "steps.meta.outputs.upgrade_from_tag",
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
            smoke.index("Build the signed release APK"),
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
