import unittest
from pathlib import Path


class EmulatorContractTests(unittest.TestCase):
    def test_smoke_script_is_executable(self):
        mode = Path("scripts/emulator_smoke.sh").stat().st_mode
        self.assertNotEqual(0, mode & 0o111)

    def test_smoke_script_upgrades_before_a_sustained_cold_launch(self):
        text = Path("scripts/emulator_smoke.sh").read_text()
        self.assertIn('adb install "$OLD_APK"', text)
        self.assertIn('adb install -r "$NEW_APK"', text)
        self.assertIn('adb shell am force-stop "$PACKAGE_ID"', text)
        self.assertIn("adb shell am start -W", text)
        self.assertIn('adb shell pidof -s "$PACKAGE_ID"', text)
        self.assertIn("dumpsys activity activities", text)
        # The window is a parameter now so the suite can run it fast, but the
        # default the emulator uses is still twenty seconds.
        self.assertIn("STABILITY_WINDOW_SECONDS=${STABILITY_WINDOW_SECONDS:-20}", text)
        self.assertIn('for stable_second in $(seq 1 "$STABILITY_WINDOW_SECONDS")', text)
        self.assertLess(
            text.index('adb install -r "$NEW_APK"'),
            text.index('adb shell am force-stop "$PACKAGE_ID"'),
        )
        self.assertLess(
            text.index('adb shell am force-stop "$PACKAGE_ID"'),
            text.index("adb shell am start -W"),
        )
        self.assertNotIn("adb shell monkey", text)

    def test_smoke_script_fails_on_crash_dead_process_or_wrong_ui(self):
        text = Path("scripts/emulator_smoke.sh").read_text()

        for required in (
            "assert_no_app_crash",
            "assert_no_app_crash.py",
            "process died during stability window",
            "tech.ula.library.MainActivity",
            "adb logcat -b crash -d",
            "uiautomator dump",
            "ui.xml",
            "screenshot.png",
        ):
            self.assertIn(required, text)

    def test_missing_pid_reaches_the_explicit_runtime_failure(self):
        text = Path("scripts/emulator_smoke.sh").read_text()

        self.assertIn("read_package_pid() {", text)
        self.assertIn("resumed_pid=$(read_package_pid)", text)
        self.assertIn(
            '[[ -n $resumed_pid ]] || fail "process missing after All Files Access return"',
            text,
        )

    def test_smoke_script_verifies_r2_metadata_certificate_and_permissions(self):
        text = Path("scripts/emulator_smoke.sh").read_text()

        for required in (
            "EXPECTED_VERSION_NAME",
            "2026.08.29-r3",
            "apksigner verify --verbose --print-certs",
            "82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC",
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.MANAGE_EXTERNAL_STORAGE",
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
            "android.permission.RECORD_AUDIO",
            "android.permission.CAMERA",
            "MANAGE_EXTERNAL_STORAGE deny",
            "MANAGE_EXTERNAL_STORAGE allow",
            "assert_visible_window.py",
            "com.android.settings",
            "com.android.permissioncontroller",
        ):
            self.assertIn(required, text)

    def test_exit_trap_always_captures_runtime_evidence(self):
        text = Path("scripts/emulator_smoke.sh").read_text()

        self.assertIn("trap capture_evidence EXIT", text)
        for filename in (
            "logcat.txt",
            "crash-buffer.txt",
            "activity.txt",
            "window.txt",
            "final-package.txt",
            "appops.txt",
            "permissions.txt",
        ):
            self.assertIn(filename, text)


if __name__ == "__main__":
    unittest.main()


class FirstRunGateContractTests(unittest.TestCase):
    def script(self) -> str:
        return Path("scripts/emulator_smoke.sh").read_text(encoding="utf-8")

    def test_the_gate_runs_a_clean_install_not_only_an_upgrade(self):
        text = self.script()
        # r2 only ever exercised an upgrade over an already-extracted filesystem.
        self.assertIn('adb shell pm clear "$PACKAGE_ID"', text)
        self.assertIn("clearing app data for a clean first run", text)

    def test_the_gate_waits_by_condition_never_by_a_fixed_download_duration(self):
        text = self.script()
        self.assertIn("wait_for_condition ", text)
        self.assertIn("downloads_are_complete", text)
        self.assertIn("extraction_succeeded", text)
        # Progress every minute; a silent half-hour job looks hung.
        self.assertIn("still waiting (${waited}s of ${timeout}s)", text)

    def test_the_gate_requires_root_rather_than_skipping_its_checks(self):
        text = self.script()
        self.assertIn("adb root", text)
        self.assertIn("adb root unavailable", text)

    def test_every_success_marker_must_have_a_working_filesystem(self):
        text = self.script()
        body = text.split("assert_filesystem_anchors() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("$root/bin/sh", body)
        self.assertIn("$root/etc/passwd", body)
        for anchor in ("nosudo", "userland_profile.sh", "ld.so.preload"):
            self.assertIn(anchor, body)

    def test_the_gate_rejects_the_failures_r2_could_not_see(self):
        text = self.script()
        for signature in (
            "CANNOT LINK EXECUTABLE",
            "addNonRootUser\\.sh: not found",
            "IncorrectSessionTransition",
        ):
            self.assertIn(signature, text)
        self.assertIn("unfinished transfers", text)
        self.assertIn("assert_payload_digests.py", text)

    def test_the_gate_interrupts_the_network_once_to_prove_resume(self):
        text = self.script()
        self.assertIn("interrupt_network_once", text)
        self.assertIn("svc data disable", text)
        self.assertIn("svc data enable", text)

    def test_taps_are_derived_from_the_ui_tree(self):
        text = self.script()
        self.assertIn("find_ui_node.py", text)
        # A hard-coded coordinate silently drifts with density and API level.
        self.assertNotRegex(text, r"adb shell input tap \d+ \d+")


class FirstRunWorkflowContractTests(unittest.TestCase):
    def workflow(self) -> str:
        return Path(".github/workflows/upgrade-smoke.yml").read_text(encoding="utf-8")

    def test_the_matrix_covers_both_api_levels(self):
        text = self.workflow()
        self.assertIn("api-level: [35, 36]", text)
        self.assertIn("api-level: ${{ matrix.api-level }}", text)

    def test_the_release_requires_twenty_bundles(self):
        text = self.workflow()
        self.assertIn('test "${#bundles[@]}" -eq 20', text)
        self.assertIn('test "$count" -eq 10', text)

    def test_the_release_requires_first_run_evidence_not_just_a_launch(self):
        text = self.workflow()
        for required in (
            "result.txt", "setup-complete.png", "relaunch.png",
            "download-journal.json", "payload-digest-report.txt",
            "success-markers.txt", "services.txt",
        ):
            self.assertIn(required, text)
        # A run that recorded either of these did not pass.
        self.assertIn('test ! -s "$bundle/pending-parts.txt"', text)
        self.assertIn('test ! -s "$bundle/forbidden-signatures.txt"', text)

