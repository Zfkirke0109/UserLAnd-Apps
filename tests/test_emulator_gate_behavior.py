"""Run the emulator gate against simulated devices.

The gate exists to refuse a broken first run. Asserting on its source text only
proves the words are present, so each case here runs the real script against a
device that is wrong in one specific way and requires the gate to fail.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "scripts/emulator_smoke.sh"
PACKAGE = "tech.ula.foxbox_pro"

UI = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node package="tech.ula.foxbox_pro" text="FoxBox" clickable="true"
        resource-id="tech.ula.foxbox_pro:id/app_row" bounds="[0,200][1080,400]"/>
  <node package="android" resource-id="android:id/button1" text="OK"
        clickable="true" bounds="[600,900][900,1000]"/>
</hierarchy>
"""

ASSETS_DIGEST = "a" * 64
ROOTFS_DIGEST = "b" * 64


def journal(state="COMPLETE", items=None):
    if items is None:
        items = [
            {"id": "assets", "state": "COMPLETE", "sha256": ASSETS_DIGEST},
            {"id": "rootfs", "state": "COMPLETE", "sha256": ROOTFS_DIGEST},
        ]
    return json.dumps({"session_id": 1, "filesystem_id": 1, "state": state, "items": items})


class EmulatorGateBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.device = self.work / "device"
        self.bin = self.work / "bin"
        self.bin.mkdir(parents=True)
        self.evidence = self.work / "evidence"

        shim = self.bin / "adb"
        shim.write_text(
            f"#!/usr/bin/env bash\nexec {sys.executable} "
            f"{REPO / 'tests/fake_device/fake_adb.py'} \"$@\"\n"
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

        # The r2 phase inspects the APK itself, so those tools are stubbed to
        # report a correctly signed APK with exactly the expected permissions.
        aapt = self.bin / "aapt"
        aapt.write_text(
            "#!/usr/bin/env bash\n"
            "echo uses-permission: name='android.permission.POST_NOTIFICATIONS'\n"
            "echo uses-permission: name='android.permission.MANAGE_EXTERNAL_STORAGE'\n"
            "echo uses-permission: name='android.permission.FOREGROUND_SERVICE_SPECIAL_USE'\n"
        )
        aapt.chmod(aapt.stat().st_mode | stat.S_IEXEC)
        signer = self.bin / "apksigner"
        signer.write_text(
            "#!/usr/bin/env bash\n"
            "echo 'Signer #1 certificate SHA-256 digest: "
            "829a556fc58ad5249b5d4c4a7fcb9a969cff3826aa5c7e4102c313b220a45fec'\n"
        )
        signer.chmod(signer.stat().st_mode | stat.S_IEXEC)

        self.lock = self.work / "payloads.lock.json"
        self.lock.write_text(json.dumps({
            "schema_version": 1,
            "apps": [{
                "id": "foxbox", "package_id": PACKAGE,
                "repository": "r", "release": "v7.7.9",
                "abis": {"x86_64": {
                    "asset_list": ["busybox"],
                    "assets.tar.gz": {"filename": "f", "release": "v7.7.9", "url": "u",
                                      "size": 1, "sha256": ASSETS_DIGEST},
                    "rootfs.tar.gz": {"filename": "f", "release": "v7.7.9", "url": "u",
                                      "size": 1, "sha256": ROOTFS_DIGEST},
                }},
            }],
        }))

    def build_device(self, *, marker=True, anchors=True, parts=False,
                     support=True, batch_state="COMPLETE", items=None,
                     failure_marker=False):
        files = self.device / f"data/user/0/{PACKAGE}/files"
        fs = files / "1"
        (fs / "support").mkdir(parents=True)
        (files / "downloads").mkdir(parents=True)
        (files / "downloads/download-journal.json").write_text(journal(batch_state, items))
        if marker:
            (fs / "support/.success_filesystem_extraction").write_text("")
        if failure_marker:
            (fs / "support/.failure_filesystem_extraction").write_text("")
        if anchors:
            (fs / "bin").mkdir()
            (fs / "bin/sh").write_text("")
            (fs / "etc").mkdir()
            (fs / "etc/passwd").write_text("")
        if support:
            for name in ("nosudo", "userland_profile.sh", "ld.so.preload"):
                (fs / "support" / name).write_text("")
        if parts:
            (files / "downloads/rootfs.tar.gz.part").write_text("")

    def run_gate(self, **scenario):
        config = {"ui": UI, "rooted": True, "extract_polls": 1, "logcat": ""}
        config.update(scenario)
        path = self.work / "scenario.json"
        path.write_text(json.dumps(config))

        env = dict(os.environ)
        env.update(
            PATH=f"{self.bin}:{env['PATH']}",
            FAKE_DEVICE=str(path),
            FAKE_DEVICE_ROOT=str(self.device),
            PAYLOAD_LOCK=str(self.lock),
            SETUP_TIMEOUT_SECONDS="6",
            UI_TIMEOUT_SECONDS="4",
            POLL_INTERVAL_SECONDS="1",
            DIALOG_SETTLE_SECONDS="0",
            NETWORK_OUTAGE_SECONDS="0",
            RELAUNCH_SETTLE_SECONDS="0",
            STABILITY_WINDOW_SECONDS="1",
        )
        env.pop("ANDROID_API_LEVEL", None)
        return subprocess.run(
            [str(GATE), PACKAGE, "old.apk", "new.apk", str(self.evidence), "2026.08.29-r3", "35"],
            capture_output=True, text=True, env=env, timeout=300,
        )

    # ---------------------------------------------------------------- passing

    def test_a_healthy_first_run_passes(self):
        self.build_device()
        result = self.run_gate()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Runtime verified for", result.stdout)
        # The whole first-run path ran, in order.
        for stage in (
            "clearing app data for a clean first run",
            "starting setup from the app list",
            "interrupting network to prove the transfer resumes",
            "every payload to download and verify",
            "payload digests match the release lock",
            "the filesystem to finish extracting",
            "filesystem anchors verified",
            "session service verified",
            "relaunching to prove the finished filesystem is reused",
        ):
            self.assertIn(stage, result.stdout, stage)

    def test_a_journal_cleared_after_staging_still_verifies_digests(self):
        """The app deletes the journal the moment it stages the downloads.

        Release run 3 failed all twenty jobs here: the gate waited for the
        journal to read COMPLETE, then read it a second time for the digests
        and found it emptied. The batch must be captured on the read that
        observed it, not fetched again afterwards.
        """
        self.build_device()
        result = self.run_gate(clear_journal_after_read=2)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("payload digests match the release lock", result.stdout)
        # The captured batch must survive into the evidence, not be overwritten
        # by the emptied file the device is left holding.
        captured = self.evidence / "download-journal.json"
        self.assertTrue(captured.is_file())
        self.assertIn("COMPLETE", captured.read_text())

    # ---------------------------------------------------------------- failing

    def test_a_success_marker_without_a_shell_is_rejected(self):
        # The exact r2 defect: a marker over a filesystem that never extracted.
        self.build_device(anchors=False)
        result = self.run_gate()
        self.assertEqual(1, result.returncode)
        self.assertIn("bin/sh", result.stderr)

    def test_a_success_marker_without_support_anchors_is_rejected(self):
        self.build_device(support=False)
        result = self.run_gate()
        self.assertEqual(1, result.returncode)
        self.assertIn("support/", result.stderr)

    def test_a_dialog_raised_during_a_wait_is_cleared_and_recorded(self):
        """Setup asks for acknowledgement partway through, not only at the start.

        Between 251MB and 1000MB free the app raises a modal low-storage dialog
        and holds setup on it; the feedback and contribution prompts are modal
        too. Release run 5 cleared dialogs only while starting setup, so once the
        downloads finished nothing tapped anything and every job sat on the
        dialog for the whole thirty-minute budget.
        """
        self.build_device()
        result = self.run_gate(blocking_dialog_during_extraction=True)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Runtime verified for", result.stdout)
        # Nothing is tapped away silently.
        self.assertIn("clearing a dialog that is blocking setup", result.stdout)
        self.assertIn("Low available storage",
                      (self.evidence / "dialogs-cleared.txt").read_text())

    def test_a_failure_before_the_extraction_wait_still_reports_the_device(self):
        """The diagnosis has to run wherever the failure happens.

        Run 8 failed during the local copy, forty seconds into setup and well
        before the extraction wait was entered, so the report that would have
        said how much storage was left and what was on disk never ran at all.
        """
        self.build_device(parts=True)
        result = self.run_gate()

        self.assertEqual(1, result.returncode)
        self.assertIn("unfinished transfers", result.stderr)
        self.assertIn("extraction diagnosis", result.stdout)
        self.assertIn("free storage", result.stdout)

    def test_an_illegal_state_dialog_is_reported_not_dismissed(self):
        """A failure report is not an acknowledgement to tap past.

        Run 7 raised, one minute in, a dialog reading "gnuplot has entered an
        illegal state! Failed to extract filesystem. Failure reason: [The
        rootfs.tar.gz download could not be read (283309072 bytes on disk,
        Command failed with: 159).]" The gate tapped OK and went on waiting for a
        setup that had already given up, so the one statement of what went wrong
        was dismissed and the run spent its whole budget saying nothing.
        """
        self.build_device()
        result = self.run_gate(blocking_dialog_during_extraction=True,
                               dialog_text="gnuplot has entered an illegal state!")

        self.assertEqual(1, result.returncode)
        self.assertIn("cannot continue past", result.stderr)
        self.assertIn("illegal state", result.stderr)

    def test_setup_resetting_itself_is_reported_not_waited_out(self):
        """The quiet exit from losing the session leaves nothing to find.

        One route logs NoSessionSelectedWhenTransitionNecessary and is caught as
        a forbidden signature. The other posts ProgressBarOperationComplete and
        resets: no crash, no illegal transition, no extraction marker. Support
        files are never cleared during a first run, so during the extraction wait
        that state can only mean setup ended without attempting extraction.
        """
        self.build_device(marker=False)
        result = self.run_gate(
            logcat="State observed MainVM: ProgressBarOperationComplete"
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("reset itself", result.stderr)
        self.assertNotIn("timed out", result.stderr)
        self.assertIn("extraction diagnosis", result.stdout)

    def test_a_recorded_extraction_failure_is_reported_not_waited_out(self):
        """The app writes a verdict either way.

        Release run 5 spent the whole thirty-minute budget polling for a success
        marker and then reported only that it had timed out. When the app has
        already recorded a failure there is nothing left to wait for: stop at the
        verdict, and say what was on disk when it was reached.
        """
        self.build_device(marker=False, failure_marker=True)
        result = self.run_gate()

        self.assertEqual(1, result.returncode)
        self.assertIn("recorded an extraction failure", result.stderr)
        self.assertNotIn("timed out", result.stderr)
        # The diagnosis has to reach the job log, because the evidence bundle is
        # not always reachable when the diagnosis is what is needed.
        self.assertIn("extraction diagnosis", result.stdout)
        self.assertIn("extraction markers", result.stdout)

    def test_an_unfinished_transfer_is_rejected(self):
        self.build_device(parts=True)
        result = self.run_gate()
        self.assertEqual(1, result.returncode)
        self.assertIn("unfinished transfers", result.stderr)

    def test_a_busybox_linker_failure_is_rejected(self):
        self.build_device()
        result = self.run_gate(logcat='CANNOT LINK EXECUTABLE "busybox": library "libbusybox.so.1.37.0" not found')
        self.assertEqual(1, result.returncode)
        self.assertIn("forbidden runtime signature", result.stderr)

    def test_an_illegal_session_transition_is_rejected(self):
        self.build_device()
        result = self.run_gate(logcat="IncorrectSessionTransition(event=SessionSelected)")
        self.assertEqual(1, result.returncode)
        self.assertIn("forbidden runtime signature", result.stderr)

    def test_setup_losing_its_session_is_rejected(self):
        """Setup that loses the session it was preparing resets itself silently.

        No crash, no illegal transition, no extraction marker — the run simply
        stops, which is why runs 5 and 6 waited out the whole budget without
        anything to report.
        """
        self.build_device()
        result = self.run_gate(
            logcat="State observed MainVM: NoSessionSelectedWhenTransitionNecessary"
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("forbidden runtime signature", result.stderr)

    def test_a_fatal_exception_in_the_target_app_is_rejected(self):
        self.build_device()
        result = self.run_gate(
            logcat=f"FATAL EXCEPTION: main\n  Process: {PACKAGE}, PID: 4242\n  java.lang.RuntimeException"
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("fatal", result.stderr.lower())

    def test_a_payload_digest_outside_the_lock_is_rejected(self):
        self.build_device(items=[
            {"id": "assets", "state": "COMPLETE", "sha256": ASSETS_DIGEST},
            {"id": "rootfs", "state": "COMPLETE", "sha256": "c" * 64},
        ])
        result = self.run_gate()
        self.assertEqual(1, result.returncode)
        self.assertIn("digests do not match", result.stderr)

    def test_an_incomplete_payload_is_rejected(self):
        self.build_device(items=[
            {"id": "assets", "state": "COMPLETE", "sha256": ASSETS_DIGEST},
            {"id": "rootfs", "state": "IN_PROGRESS", "sha256": ROOTFS_DIGEST},
        ])
        result = self.run_gate()
        self.assertEqual(1, result.returncode)

    def test_a_missing_extraction_marker_times_out_rather_than_passing(self):
        self.build_device(marker=False)
        result = self.run_gate()
        self.assertEqual(1, result.returncode)
        self.assertIn("extract", result.stderr.lower())

    def test_a_dead_session_service_is_rejected(self):
        self.build_device()
        result = self.run_gate(services="(nothing)")
        self.assertEqual(1, result.returncode)
        self.assertIn("service", result.stderr.lower())

    def test_an_unrooted_device_cannot_vouch_for_the_run(self):
        self.build_device()
        result = self.run_gate(rooted=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("adb root", result.stderr)

    # ---------------------------------------------------------------- evidence

    def test_evidence_is_captured_even_when_the_run_fails(self):
        self.build_device(anchors=False)
        self.run_gate()
        for name in ("logcat.txt", "crash-buffer.txt", "activity.txt", "services.txt"):
            self.assertTrue((self.evidence / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
