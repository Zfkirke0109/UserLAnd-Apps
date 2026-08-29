import hashlib
import inspect
import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from tools.apply_compat import apply_profile, load_profile


class CompatibilityTests(unittest.TestCase):
    def test_apply_profile_accepts_a_bounded_replacement_asset_root(self):
        self.assertIn("assets_root", inspect.signature(apply_profile).parameters)

    def test_replace_file_requires_old_hash_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            assets = base / "assets"
            target = root / "src/PermissionHandler.kt"
            source = assets / "compat/PermissionHandler.kt"
            target.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            target.write_text("old source\n", encoding="utf-8")
            source.write_text("r2 source\n", encoding="utf-8")
            old_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
            profile = {
                "operations": [
                    {
                        "type": "replace_file",
                        "path": "src/PermissionHandler.kt",
                        "source": "compat/PermissionHandler.kt",
                        "old_sha256": old_sha256,
                    }
                ]
            }

            try:
                changed = apply_profile(root, profile, assets_root=assets)
            except ValueError as error:
                self.fail(f"replace_file should be supported: {error}")

            self.assertEqual(["src/PermissionHandler.kt"], changed)
            self.assertEqual("r2 source\n", target.read_text(encoding="utf-8"))
            self.assertEqual([], apply_profile(root, profile, assets_root=assets))

    def test_replace_file_rejects_wrong_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            assets = base / "assets"
            (root / "target").parent.mkdir(parents=True)
            (root / "target").write_text("old", encoding="utf-8")
            (assets / "source").parent.mkdir(parents=True)
            (assets / "source").write_text("new", encoding="utf-8")
            profile = {
                "operations": [
                    {
                        "type": "replace_file",
                        "path": "target",
                        "source": "source",
                        "old_sha256": "0" * 64,
                    }
                ]
            }

            with self.assertRaisesRegex(ValueError, "old SHA-256 mismatch"):
                apply_profile(root, profile, assets_root=assets)

    def test_replace_file_rejects_asset_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            assets = base / "assets"
            root.mkdir()
            assets.mkdir()
            target = root / "target"
            target.write_text("old", encoding="utf-8")
            (base / "outside").write_text("new", encoding="utf-8")
            profile = {
                "operations": [
                    {
                        "type": "replace_file",
                        "path": "target",
                        "source": "../outside",
                        "old_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    }
                ]
            }

            with self.assertRaisesRegex(ValueError, "asset escapes directory"):
                apply_profile(root, profile, assets_root=assets)

    def test_copy_file_creates_exact_asset_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            assets = base / "assets"
            source = assets / "compat/r3/NewRuntime.kt"
            root.mkdir()
            source.parent.mkdir(parents=True)
            source.write_text("package example\n", encoding="utf-8")
            profile = {
                "operations": [
                    {
                        "type": "copy_file",
                        "path": "src/NewRuntime.kt",
                        "source": "compat/r3/NewRuntime.kt",
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                ]
            }

            changed = apply_profile(root, profile, assets_root=assets)

            target = root / "src/NewRuntime.kt"
            self.assertEqual(["src/NewRuntime.kt"], changed)
            self.assertEqual(b"package example\n", target.read_bytes())
            self.assertEqual([], apply_profile(root, profile, assets_root=assets))

    def test_copy_file_rejects_source_or_destination_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            assets = base / "assets"
            root.mkdir()
            assets.mkdir()
            outside = base / "outside.kt"
            outside.write_text("outside\n", encoding="utf-8")
            digest = hashlib.sha256(outside.read_bytes()).hexdigest()

            cases = (
                ("src/NewRuntime.kt", "../outside.kt"),
                ("../outside-target.kt", "inside.kt"),
            )
            (assets / "inside.kt").write_text("outside\n", encoding="utf-8")
            for target, source in cases:
                with self.subTest(target=target, source=source):
                    profile = {
                        "operations": [
                            {
                                "type": "copy_file",
                                "path": target,
                                "source": source,
                                "sha256": digest,
                            }
                        ]
                    }
                    with self.assertRaisesRegex(ValueError, "escapes"):
                        apply_profile(root, profile, assets_root=assets)

    def test_copy_file_rejects_conflicting_existing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            assets = base / "assets"
            target = root / "src/NewRuntime.kt"
            source = assets / "compat/r3/NewRuntime.kt"
            target.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            target.write_text("user bytes\n", encoding="utf-8")
            source.write_text("r3 bytes\n", encoding="utf-8")
            profile = {
                "operations": [
                    {
                        "type": "copy_file",
                        "path": "src/NewRuntime.kt",
                        "source": "compat/r3/NewRuntime.kt",
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                ]
            }

            with self.assertRaisesRegex(
                ValueError, "target already exists with different bytes"
            ):
                apply_profile(root, profile, assets_root=assets)

            self.assertEqual("user bytes\n", target.read_text(encoding="utf-8"))

    def test_copy_file_rejects_source_hash_mismatch_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "workspace"
            assets = base / "assets"
            source = assets / "compat/r3/NewRuntime.kt"
            root.mkdir()
            source.parent.mkdir(parents=True)
            source.write_text("r3 bytes\n", encoding="utf-8")
            profile = {
                "operations": [
                    {
                        "type": "copy_file",
                        "path": "src/NewRuntime.kt",
                        "source": "compat/r3/NewRuntime.kt",
                        "sha256": "0" * 64,
                    }
                ]
            }

            with self.assertRaisesRegex(ValueError, "source SHA-256 mismatch"):
                apply_profile(root, profile, assets_root=assets)

            self.assertFalse((root / "src/NewRuntime.kt").exists())

    def test_r2_permission_handler_uses_api_and_feature_appropriate_access(self):
        overlay = Path("compat/r2/PermissionHandler.kt")
        self.assertTrue(overlay.is_file(), "r2 permission handler must exist")
        text = overlay.read_text(encoding="utf-8")

        for required in (
            "Build.VERSION.SDK_INT >= Build.VERSION_CODES.R",
            "Environment.isExternalStorageManager()",
            "Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION",
            "Manifest.permission.POST_NOTIFICATIONS",
            "BuildConfig.USES_MICROPHONE",
            "grantResults.indices.all",
            "pendingAllFilesAccessRequest",
        ):
            self.assertIn(required, text)
        self.assertNotIn("grantResults[0]", text)
        self.assertNotIn("grantResults[1]", text)
        self.assertNotIn("Manifest.permission.CAMERA", text)

    def test_r2_profile_replaces_the_exact_locked_permission_handler(self):
        profile = load_profile(Path("profiles/andacious.json"))

        self.assertTrue(
            any(
                operation.get("type") == "replace_file"
                and operation.get("path")
                == "UserLAndLibrary/app/src/main/java/tech/ula/library/utils/PermissionHandler.kt"
                and operation.get("source") == "compat/r2/PermissionHandler.kt"
                and operation.get("old_sha256")
                == "b4f0cc790ad2faadc8317a67515fd56defd4a3b08b218f80d6f674617ef60400"
                for operation in profile["operations"]
            )
        )

    def test_r3_profile_replaces_busybox_executor_and_copies_behavior_test(self):
        profile = load_profile(Path("profiles/andacious.json"))
        operations = profile["operations"]

        self.assertTrue(
            any(
                operation.get("type") == "replace_file"
                and operation.get("path")
                == "UserLAndLibrary/app/src/main/java/tech/ula/library/utils/BusyboxExecutor.kt"
                and operation.get("source")
                == "compat/r3/java/tech/ula/library/utils/BusyboxExecutor.kt"
                and operation.get("old_sha256")
                == "a0616c39d47c6f05e5fe50564de00bcac8a2f5d499fbe773c2fe73eacd6dc6c3"
                for operation in operations
            )
        )
        self.assertTrue(
            any(
                operation.get("type") == "copy_file"
                and operation.get("path", "").endswith("R3BusyboxExecutorTest.kt")
                for operation in operations
            )
        )

    def test_r3_filesystem_manager_extracts_before_it_trusts_a_success_marker(self):
        overlay = Path("compat/r3/java/tech/ula/library/utils/FilesystemManager.kt")
        self.assertTrue(overlay.is_file(), "r3 filesystem manager must exist")
        text = overlay.read_text(encoding="utf-8")

        for required in (
            "fun validateRootfsArchive(",
            "fun hasUsableFilesystem(",
            'startsWith("/")',
            'split(\'/\').any { it == ".." }',
            'runHostApplet(\n            "tar"',
            '"/support/common/addNonRootUser.sh"',
            'listOf("bin/sh", "etc/passwd")',
            'listOf("nosudo", "userland_profile.sh", "ld.so.preload")',
            "successMarker.delete()",
            "successMarker.createNewFile()",
        ):
            self.assertIn(required, text)

        # The v1.5.1 helper no longer extracts, so the runtime must not delegate to it.
        self.assertNotIn("extractFilesystem.sh", text)
        # A failed stage must leave the download in place for Retry.
        self.assertEqual(1, text.count("archive.delete()"))
        # An exclusion only matches the stored member name, so both shapes are passed.
        self.assertIn('listOf("--exclude", it, "--exclude", "./$it")', text)

    def test_r3_archive_validation_rejects_unsafe_members_before_extraction(self):
        overlay = Path("compat/r3/java/tech/ula/library/utils/FilesystemManager.kt")
        text = overlay.read_text(encoding="utf-8")

        validation = text.split("fun validateRootfsArchive(", 1)[1]
        validation = validation.split("\n    /**", 1)[0]

        self.assertIn("members.any { it.isUnsafeArchiveMember() }", validation)
        self.assertIn('runHostApplet(\n            "tar",\n            listOf("-tzf"', validation)
        # The rejected member name is attacker-controlled and must not be echoed back.
        self.assertNotIn("$it", validation.split("isUnsafeArchiveMember() }", 1)[1])

        extraction = text.split("suspend fun extractFilesystem(", 1)[1]
        extraction = extraction.split("suspend fun compressFilesystem(", 1)[0]
        self.assertLess(
            extraction.index("validateRootfsArchive(archive)"),
            extraction.index('runHostApplet(\n            "tar",\n            extractionArguments'),
        )

    def test_r3_filesystem_manager_verifies_anchors_before_writing_success(self):
        overlay = Path("compat/r3/java/tech/ula/library/utils/FilesystemManager.kt")
        text = overlay.read_text(encoding="utf-8")

        extraction = text.split("suspend fun extractFilesystem(", 1)[1]
        extraction = extraction.split("suspend fun compressFilesystem(", 1)[0]

        verification = extraction.index("missingFilesystemAnchor(")
        for earlier in ("runHostApplet(", "executeProotCommand("):
            self.assertLess(extraction.index(earlier), verification, earlier)
        self.assertLess(verification, extraction.index("successMarker.createNewFile()"))

    def test_r3_usable_filesystem_requires_anchors_and_not_only_the_marker(self):
        overlay = Path("compat/r3/java/tech/ula/library/utils/FilesystemManager.kt")
        text = overlay.read_text(encoding="utf-8")

        body = text.split("fun hasUsableFilesystem(", 1)[1]
        body = body.split("\n    fun ", 1)[0]

        self.assertIn('$filesystemExtractionSuccess").exists()) return false', body)
        self.assertIn("missingFilesystemAnchor(targetDirectoryName, username) == null", body)
        # The r2 predicate returned the marker's existence and nothing else.
        self.assertNotIn("return true", body)

        delegate = text.split("fun hasFilesystemBeenSuccessfullyExtracted(", 1)[1]
        delegate = delegate.split("\n    fun ", 1)[0]
        self.assertIn("hasUsableFilesystem(targetDirectoryName)", delegate)
        self.assertNotIn("exists()", delegate)

    def test_r3_profile_replaces_filesystem_manager_and_copies_behavior_test(self):
        profile = load_profile(Path("profiles/birdbox.json"))
        operations = profile["operations"]

        self.assertTrue(
            any(
                operation.get("type") == "replace_file"
                and operation.get("path")
                == "UserLAndLibrary/app/src/main/java/tech/ula/library/utils/FilesystemManager.kt"
                and operation.get("source")
                == "compat/r3/java/tech/ula/library/utils/FilesystemManager.kt"
                and operation.get("old_sha256")
                == "e6c88329469c77894f4514e8c5a56a33b270eac32cb2a58653717211d477cee8"
                for operation in operations
            )
        )
        self.assertTrue(
            any(
                operation.get("type") == "copy_file"
                and operation.get("path", "").endswith("R3FilesystemManagerTest.kt")
                for operation in operations
            )
        )

    def test_r3_profile_retires_the_superseded_upstream_extraction_tests(self):
        profile = load_profile(Path("profiles/birdbox.json"))
        removals = [
            operation for operation in profile["operations"]
            if operation.get("type") == "replace"
            and operation.get("path", "").endswith("FilesystemManagerTest.kt")
        ]

        self.assertEqual(2, len(removals))
        # The v1.5.1 command contract and the marker-only success predicate are gone.
        self.assertTrue(
            any("/support/common/extractFilesystem.sh" in operation["old"] for operation in removals)
        )
        self.assertTrue(
            any(
                "filesystemHasOnlyBeenSuccessfullyExtractedIfSuccessStatusFileExists"
                in operation["old"]
                for operation in removals
            )
        )
        for operation in removals:
            self.assertEqual(1, operation.get("count"))
            self.assertNotIn("@Test", operation["new"])

    def test_r3_transfer_resumes_verifies_and_publishes_atomically(self):
        overlay = Path("compat/r3/java/tech/ula/library/utils/ResumableAssetTransfer.kt")
        self.assertTrue(overlay.is_file(), "r3 resumable transfer must exist")
        text = overlay.read_text(encoding="utf-8")

        for required in (
            'builder.header("Range", "bytes=$resumeFrom-")',
            "response.code == HTTP_PARTIAL_CONTENT && resumeFrom > 0",
            "const val DEFAULT_MAX_ATTEMPTS = 5",
            "MessageDigest.getInstance(\"SHA-256\")",
            "output.fd.sync()",
            "part.renameTo(destination)",
        ):
            self.assertIn(required, text)

        # Setup payloads must not go back through the OEM download provider.
        self.assertNotIn("DownloadManager", text)

    def test_r3_transfer_never_publishes_before_it_verifies(self):
        overlay = Path("compat/r3/java/tech/ula/library/utils/ResumableAssetTransfer.kt")
        text = overlay.read_text(encoding="utf-8")

        consume = text.split("private fun consume(", 1)[1]
        consume = consume.split("private fun retryable(", 1)[0]

        digest_check = consume.index("if (item.isLocked) {")
        length_check = consume.index("written != item.expectedBytes")
        publish = consume.index("publish(part, item.destinationFile)")
        self.assertLess(length_check, digest_check)
        self.assertLess(digest_check, publish)

        # A body that fails its locked digest is removed, never left behind.
        mismatch = consume[digest_check:publish]
        self.assertIn("part.delete()", mismatch)
        self.assertIn("item.destinationFile.delete()", mismatch)
        self.assertIn("terminal = true", mismatch)

    def test_r3_journal_persists_resume_state_atomically(self):
        overlay = Path("compat/r3/java/tech/ula/library/utils/DownloadJournal.kt")
        self.assertTrue(overlay.is_file(), "r3 download journal must exist")
        text = overlay.read_text(encoding="utf-8")

        for required in (
            'writer.name("session_id").value(batch.sessionId)',
            'writer.name("filesystem_id").value(batch.filesystemId)',
            'writer.name("bytes_written").value(item.bytesWritten)',
            "stream.fd.sync()",
            "temporary.renameTo(journalFile)",
        ):
            self.assertIn(required, text)

        write = text.split("fun write(", 1)[1].split("\n    fun ", 1)[0]
        # The descriptor has to still be open when it is synced, and the journal is
        # only published once those bytes are durable.
        self.assertLess(write.index("stream.fd.sync()"), write.index("renameTo(journalFile)"))

        # An unreadable journal must not be resumed from.
        read = text.split("fun read(", 1)[1].split("\n    fun ", 1)[0]
        self.assertIn("catch (err: IOException)", read)
        self.assertIn("null", read)

    def test_r3_profile_copies_the_download_transfer_overlay(self):
        profile = load_profile(Path("profiles/gimp.json"))
        copied = {
            operation.get("source"): operation.get("path")
            for operation in profile["operations"]
            if operation.get("type") == "copy_file"
        }

        for source, target in (
            ("compat/r3/java/tech/ula/library/utils/DownloadJournal.kt",
             "UserLAndLibrary/app/src/main/java/tech/ula/library/utils/DownloadJournal.kt"),
            ("compat/r3/java/tech/ula/library/utils/ResumableAssetTransfer.kt",
             "UserLAndLibrary/app/src/main/java/tech/ula/library/utils/ResumableAssetTransfer.kt"),
            ("compat/r3/test/tech/ula/library/utils/R3DownloadJournalTest.kt",
             "UserLAndLibrary/app/src/test/java/tech/ula/library/utils/R3DownloadJournalTest.kt"),
            ("compat/r3/test/tech/ula/library/utils/R3ResumableAssetTransferTest.kt",
             "UserLAndLibrary/app/src/test/java/tech/ula/library/utils/R3ResumableAssetTransferTest.kt"),
        ):
            self.assertEqual(target, copied.get(source), source)

    def test_r3_copy_file_sources_are_pinned_to_their_current_bytes(self):
        profile = load_profile(Path("profiles/gimp.json"))

        for operation in profile["operations"]:
            if operation.get("type") != "copy_file":
                continue
            source = Path(operation["source"])
            self.assertTrue(source.is_file(), operation["source"])
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(actual, operation.get("sha256"), operation["source"])

    def test_r3_service_enters_the_foreground_before_it_transfers(self):
        service = Path("compat/r3/java/tech/ula/library/AssetDownloadService.kt")
        self.assertTrue(service.is_file(), "r3 download service must exist")
        text = service.read_text(encoding="utf-8")

        start = text.split("override fun onStartCommand(", 1)[1]
        start = start.split("\n    private ", 1)[0]
        # Android stops a background service that starts long work.
        self.assertLess(start.index("startInForeground("), start.index("AssetDownloadRunner("))
        self.assertIn("FOREGROUND_SERVICE_TYPE_DATA_SYNC", text)
        self.assertIn("stopForegroundCompat()", text)
        self.assertIn("stopSelf()", text)

        # The library pins androidx.core 1.6.0, which has no typed ServiceCompat.
        self.assertNotIn("import androidx.core.app.ServiceCompat", text)
        self.assertNotIn("ServiceCompat.", text)
        # Every version-gated platform call stays behind a guard.
        for guarded in ("FOREGROUND_SERVICE_TYPE_DATA_SYNC", "FLAG_IMMUTABLE"):
            index = text.index(guarded)
            preceding = text[:index]
            self.assertIn("Build.VERSION.SDK_INT >=", preceding, guarded)

    def test_r3_runner_journals_every_state_before_announcing_it(self):
        runner = Path("compat/r3/java/tech/ula/library/utils/AssetDownloadRunner.kt")
        self.assertTrue(runner.is_file(), "r3 download runner must exist")
        text = runner.read_text(encoding="utf-8")

        loop = text.split("while (true) {", 1)[1].split("\n        val outcome", 1)[0]
        # A listener must never learn of progress a restart could not confirm.
        self.assertLess(loop.index("journal.write(batch)"), loop.index("lifecycle.onProgress("))
        self.assertIn("if (result is TransferFailed && result.terminal) break", loop)

        # Work already published is adopted before the network is touched again.
        prelude = text.split("fun run(", 1)[1].split("while (true) {", 1)[0]
        self.assertLess(prelude.index("reconcile("), prelude.index("lifecycle.onStarted("))

    def test_r3_planner_stops_a_batch_once_an_item_fails_terminally(self):
        planner = Path("compat/r3/java/tech/ula/library/utils/AssetDownloadPlanner.kt")
        self.assertTrue(planner.is_file(), "r3 download planner must exist")
        text = planner.read_text(encoding="utf-8")

        pending = text.split("fun nextPending(", 1)[1].split("\n    fun ", 1)[0]
        # Continuing past a terminal failure only spends more of the user's data.
        self.assertIn(
            "if (batch.items.any { it.state == DownloadItemState.FAILED }) return null",
            pending,
        )
        self.assertIn("fun plan(", text)
        self.assertIn("fun reconcile(", text)

    def test_r3_catalog_requires_exact_release_bytes(self):
        catalog = Path("compat/r3/java/tech/ula/library/model/repositories/LockedPayloadCatalog.kt")
        self.assertTrue(catalog.is_file(), "r3 payload catalog must exist")
        text = catalog.read_text(encoding="utf-8")

        # A payload with no URL or digest cannot be selected by exact bytes.
        self.assertIn("if (url.isBlank() || sha256.isBlank()) return null", text)
        self.assertIn('const val ROOTFS_PAYLOAD = "rootfs.tar.gz"', text)
        self.assertIn('const val ASSETS_PAYLOAD = "assets.tar.gz"', text)
        # Every URL is read from the lock, never assembled from a moving pointer.
        self.assertNotIn('"latest"', text)
        self.assertNotIn('url +', text)
        self.assertIn('"release" -> release = reader.nextString()', text)

    def test_r3_profile_declares_the_data_sync_download_service(self):
        profile = load_profile(Path("profiles/idle.json"))
        operations = "\n".join(
            json.dumps(operation, sort_keys=True) for operation in profile["operations"]
        )

        self.assertIn("android.permission.FOREGROUND_SERVICE_DATA_SYNC", operations)
        self.assertIn('android:name=\\".AssetDownloadService\\"', operations)
        self.assertIn('android:foregroundServiceType=\\"dataSync\\"', operations)
        self.assertIn('android:exported=\\"false\\"', operations)

    def test_r3_download_overlay_is_copied_into_every_app(self):
        profile = load_profile(Path("profiles/idle.json"))
        copied = {
            operation.get("source"): operation.get("path")
            for operation in profile["operations"]
            if operation.get("type") == "copy_file"
        }

        for source in (
            "compat/r3/java/tech/ula/library/model/repositories/LockedPayloadCatalog.kt",
            "compat/r3/java/tech/ula/library/utils/AssetDownloadPlanner.kt",
            "compat/r3/java/tech/ula/library/utils/AssetDownloadRunner.kt",
            "compat/r3/java/tech/ula/library/utils/AssetDownloadSignals.kt",
            "compat/r3/java/tech/ula/library/AssetDownloadService.kt",
        ):
            self.assertIn(source, copied)
            self.assertTrue(copied[source].startswith("UserLAndLibrary/app/src/main/java/"), source)

    def test_r3_switchover_removes_the_oem_download_provider(self):
        profile = load_profile(Path("profiles/birdbox.json"))
        operations = profile["operations"]
        blob = "\n".join(json.dumps(op, sort_keys=True) for op in operations)

        # The receiver, the provider handle, and its import all go.
        for removed in (
            "import android.app.DownloadManager",
            "downloadBroadcastReceiver",
            "getSystemService(Context.DOWNLOAD_SERVICE)",
        ):
            self.assertTrue(
                any(op.get("type") == "replace" and removed in op.get("old", "")
                    for op in operations),
                removed,
            )
        self.assertIn("AssetDownloadSignals.observe", blob)
        self.assertIn("AssetDownloader(assetPreferences, ulaFiles, applicationContext)", blob)

    def test_r3_switchover_operations_run_after_the_r2_ones_they_edit(self):
        profile = load_profile(Path("profiles/birdbox.json"))
        operations = profile["operations"]

        def index_of(predicate):
            return next(i for i, op in enumerate(operations) if predicate(op))

        # r2 creates the receiver registration; the switchover removes it, so the
        # ordering between them is load-bearing.
        creates = index_of(
            lambda op: op.get("type") == "replace"
            and "Context.RECEIVER_EXPORTED" in op.get("new", "")
        )
        removes = index_of(
            lambda op: op.get("type") == "replace"
            and "Context.RECEIVER_EXPORTED" in op.get("old", "")
        )
        self.assertLess(creates, removes)

    def test_r3_fsm_reattaches_to_a_download_already_running(self):
        profile = load_profile(Path("profiles/birdbox.json"))
        blob = "\n".join(json.dumps(op, sort_keys=True) for op in profile["operations"])

        # Reopening mid-download used to yield IncorrectSessionTransition.
        self.assertIn("cachedSessionId() == event.session.id", blob)
        self.assertIn("handleAssetDownloadState(assetDownloader.syncStateWithCache())", blob)
        self.assertIn("rememberSelection(session.id, filesystem.id)", blob)

    def test_devstudio_excludes_upstream_unsupported_x86_abi(self):
        profile = load_profile(Path("profiles/devstudio.json"))

        self.assertTrue(
            any(
                operation.get("path") == "app/build.gradle"
                and "abiFilters 'armeabi-v7a', 'arm64-v8a', 'x86_64'"
                in operation.get("text", "")
                for operation in profile["operations"]
            )
        )

    def test_r2_manifest_declares_android_16_storage_notification_and_service_contracts(self):
        profile = load_profile(Path("profiles/andacious.json"))
        operations = "\n".join(
            json.dumps(operation, sort_keys=True)
            for operation in profile["operations"]
        )

        for required in (
            "android.permission.ACCESS_WIFI_STATE",
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.MANAGE_EXTERNAL_STORAGE",
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
            'android:foregroundServiceType=\\"specialUse\\"',
            "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE",
            'android:maxSdkVersion=\\"29\\"',
        ):
            self.assertIn(required, operations)
        self.assertTrue(
            any(
                operation.get("old") == '<uses-permission tools:node="removeAll"/>'
                and operation.get("new") == ""
                for operation in profile["operations"]
            )
        )

    def test_r2_permission_calls_resume_without_a_denial_loop_and_leave_saf_independent(self):
        profile = load_profile(Path("profiles/andacious.json"))
        operations = "\n".join(
            operation.get("new", "") + operation.get("text", "")
            for operation in profile["operations"]
        )

        self.assertIn("forSession = true", operations)
        self.assertIn("consumeAllFilesAccessRequest", operations)
        self.assertIn(
            "permissionsWereGranted(requestCode, permissions, grantResults)",
            operations,
        )
        self.assertIn("viewModel.handleUserInputCancelled()", operations)
        self.assertIn("ContextCompat.startForegroundService", operations)
        self.assertTrue(
            any(
                operation.get("type") == "insert_after"
                and operation.get("path", "").endswith("MainActivity.kt")
                and operation.get("anchor")
                == "    override fun onResume() {\n        super.onResume()\n"
                and "consumeAllFilesAccessRequest" in operation.get("text", "")
                for operation in profile["operations"]
            )
        )
        self.assertFalse(
            any(
                operation.get("path", "").endswith("MainActivity.kt")
                and "override fun onResume()" in operation.get("new", "")
                for operation in profile["operations"]
            )
        )
        self.assertTrue(
            any(
                operation.get("path", "").endswith("FilesystemListFragment.kt")
                and "PermissionHandler.permissionsAreGranted" in operation.get("old", "")
                and operation.get("new") == ""
                for operation in profile["operations"]
            )
        )
        self.assertTrue(
            any(
                operation.get("path", "").endswith("FilesystemEditFragment.kt")
                and "PermissionHandler.permissionsAreGranted" in operation.get("old", "")
                and operation.get("new") == ""
                for operation in profile["operations"]
            )
        )

    def test_android_14_download_receiver_declares_external_sender_access(self):
        profile = load_profile(Path("profiles/andacious.json"))
        operations = [
            operation
            for operation in profile["operations"]
            if operation.get("path")
            == "UserLAndLibrary/app/src/main/java/tech/ula/library/MainActivity.kt"
        ]

        self.assertTrue(
            any(
                "registerReceiver(\n            downloadBroadcastReceiver" in operation.get(
                    "old", ""
                )
                and "Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU"
                in operation.get("new", "")
                and "Context.RECEIVER_EXPORTED" in operation.get("new", "")
                and "ContextCompat.RECEIVER_EXPORTED"
                not in operation.get("new", "")
                and "DownloadManager.ACTION_DOWNLOAD_COMPLETE"
                in operation.get("new", "")
                for operation in operations
            )
        )

    def test_r2_session_selection_falls_back_to_room_when_livedata_is_stale(self):
        profile = load_profile(Path("profiles/andacious.json"))
        operations = profile["operations"]

        self.assertTrue(
            any(
                operation.get("path")
                == "UserLAndLibrary/app/src/main/java/tech/ula/library/model/daos/FilesystemDao.kt"
                and "getFilesystemById" in operation.get("text", "")
                and "Filesystem?" in operation.get("text", "")
                for operation in operations
            )
        )
        session_fix = next(
            operation
            for operation in operations
            if operation.get("path")
            == "UserLAndLibrary/app/src/main/java/tech/ula/library/model/state/SessionStartupFsm.kt"
            and "findFilesystemForSession" in operation.get("old", "")
        )
        replacement = session_fix.get("new", "")
        self.assertIn("filesystems.find", replacement)
        self.assertIn("filesystemDao.getFilesystemById", replacement)
        self.assertIn("withContext(Dispatchers.IO)", replacement)
        self.assertIn("SessionFilesystemUnavailable", replacement)
        self.assertNotIn("!!", replacement)
        self.assertTrue(
            any(
                operation.get("path")
                == "UserLAndLibrary/app/src/main/java/tech/ula/library/viewmodel/MainActivityViewModel.kt"
                and "SessionFilesystemUnavailable" in operation.get("text", "")
                and "NoSessionSelectedWhenTransitionNecessary"
                in operation.get("text", "")
                for operation in operations
            )
        )

    def test_r2_launcher_feature_permissions_are_minimized(self):
        andacious = Path("apps/andacious/app/src/main/AndroidManifest.xml").read_text()
        self.assertNotIn(
            'android.permission.RECORD_AUDIO" tools:node="remove"', andacious
        )
        for name in (
            "foxbox",
            "gnuplot",
            "r",
            "libredocs",
            "devstudio",
            "inkscape",
            "birdbox",
            "gimp",
            "idle",
        ):
            with self.subTest(name=name):
                manifest = Path(
                    f"apps/{name}/app/src/main/AndroidManifest.xml"
                ).read_text()
                self.assertIn(
                    'android.permission.RECORD_AUDIO" tools:node="remove"',
                    manifest,
                )
        for name in (
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
            manifest = Path(f"apps/{name}/app/src/main/AndroidManifest.xml").read_text()
            self.assertIn(
                'android.permission.CAMERA" tools:node="remove"', manifest
            )

    def test_modern_navigation_has_valid_inflation_destination(self):
        nav_path = (
            "UserLAndLibrary/app/src/main/res/navigation/nav_graph.xml"
        )
        activity_path = (
            "UserLAndLibrary/app/src/main/java/tech/ula/library/MainActivity.kt"
        )
        profile = load_profile(Path("profiles/andacious.json"))
        navigation_operations = [
            operation
            for operation in profile["operations"]
            if operation.get("path") == nav_path
            or (
                operation.get("path") == activity_path
                and "startDestination" in operation.get("old", "")
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nav = root / nav_path
            nav.parent.mkdir(parents=True)
            nav.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<!-- app:navGraph is defined dynamically so that '
                'startDestination can be defined dynamically\n'
                '    according to user preference -->\n'
                '<navigation xmlns:app="http://schemas.android.com/apk/res-auto"\n'
                '    xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    xmlns:tools="http://schemas.android.com/tools" >\n'
                '    <fragment android:id="@+id/app_list_fragment" />\n'
                '</navigation>\n',
                encoding="utf-8",
            )
            activity = root / activity_path
            activity.parent.mkdir(parents=True)
            activity.write_text(
                "        graph.startDestination = when (userPreference) {\n"
                "            getString(R.string.sessions) -> "
                "R.id.session_list_fragment\n"
                "            else -> R.id.app_list_fragment\n"
                "        }\n"
                "        navController.graph = graph\n",
                encoding="utf-8",
            )

            apply_profile(root, {"operations": navigation_operations})

            navigation = ET.parse(nav).getroot()
            self.assertEqual(
                "@id/app_list_fragment",
                navigation.get(
                    "{http://schemas.android.com/apk/res-auto}startDestination"
                ),
            )
            main_activity = activity.read_text(encoding="utf-8")
            self.assertIn("graph.setStartDestination", main_activity)
            self.assertLess(
                main_activity.index("graph.setStartDestination"),
                main_activity.index("navController.graph = graph"),
            )
            self.assertNotIn("defined dynamically", nav.read_text())

    def test_all_r2_profiles_add_modern_dependency_namespaces(self):
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
        self.assertTrue(has_bvnc_namespace(legacy))

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
                operation.get("path") == "build.gradle"
                and operation.get("old") == "kotlin_version = '1.9.20'"
                and operation.get("new") == "kotlin_version = '1.7.20'"
                for operation in legacy["operations"]
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
        self.assertEqual(1, len(scaling_defaults(legacy)))

    def test_modern_profiles_upgrade_moshi_metadata_parser(self):
        modern = load_profile(Path("profiles/andacious.json"))
        legacy = load_profile(Path("profiles/foxbox.json"))

        def has_moshi_upgrade(profile):
            return any(
                operation.get("path") == "UserLAndLibrary/app/build.gradle"
                and operation.get("old") == "def moshi_version = '1.12.0'"
                and operation.get("new") == "def moshi_version = '1.14.0'"
                for operation in profile["operations"]
            )

        self.assertTrue(has_moshi_upgrade(modern))
        self.assertTrue(has_moshi_upgrade(legacy))

    def test_modern_profiles_bridge_androidx_and_kotlin_api_changes(self):
        modern = load_profile(Path("profiles/andacious.json"))
        legacy = load_profile(Path("profiles/foxbox.json"))

        def changes(profile):
            return profile["operations"]

        self.assertTrue(
            any(
                operation.get("path") == "gradle.properties"
                and "android.nonTransitiveRClass=false"
                in operation.get("text", "")
                for operation in changes(modern)
            )
        )
        self.assertTrue(
            any(
                operation.get("path")
                == "UserLAndLibrary/app/src/main/java/tech/ula/library/MainActivity.kt"
                and "graph.setStartDestination" in operation.get("new", "")
                for operation in changes(modern)
            )
        )
        factory_paths = {
            operation.get("path")
            for operation in changes(modern)
            if operation.get("old")
            == "override fun <T : ViewModel?> create(modelClass: Class<T>): T"
            and operation.get("new")
            == "override fun <T : ViewModel> create(modelClass: Class<T>): T"
        }
        self.assertEqual(
            {
                "UserLAndLibrary/app/src/main/java/tech/ula/library/viewmodel/AppDetailsViewModel.kt",
                "UserLAndLibrary/app/src/main/java/tech/ula/library/viewmodel/FilesystemEditViewModel.kt",
                "UserLAndLibrary/app/src/main/java/tech/ula/library/viewmodel/FilesystemListViewModel.kt",
                "UserLAndLibrary/app/src/main/java/tech/ula/library/viewmodel/MainActivityViewModel.kt",
                "UserLAndLibrary/app/src/main/java/tech/ula/library/viewmodel/SessionEditViewModel.kt",
            },
            factory_paths,
        )
        self.assertEqual(
            2,
            sum(
                "else -> Unit" in operation.get("text", "")
                for operation in changes(modern)
            ),
        )
        self.assertTrue(
            any(
                "android.nonTransitiveRClass=false" in operation.get("text", "")
                for operation in changes(legacy)
            )
        )

    def test_foxbox_uses_current_modern_version_anchor(self):
        profile = load_profile(Path("profiles/foxbox.json"))

        self.assertTrue(
            any(
                operation.get("path") == "build.gradle"
                and operation.get("anchor")
                == "        appVersionName = '24.11.27'\n"
                and "compileApi = 35" in operation.get("text", "")
                and "targetApi = 35" in operation.get("text", "")
                for operation in profile["operations"]
            )
        )
        self.assertFalse(
            any(
                operation.get("path") == "build.gradle"
                and operation.get("anchor")
                == "        appVersionName = '0.0.1'\n"
                for operation in profile["operations"]
            )
        )

    def test_all_r2_profiles_select_support_assets_v1_5_1(self):
        for name in (
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
            with self.subTest(name=name):
                profile = load_profile(Path(f"profiles/{name}.json"))
                self.assertTrue(
                    any(
                        operation.get("path") == "UserLAndLibrary/app/build.gradle"
                        and operation.get("old") == 'def assetVersion = "v1.3.4"'
                        and operation.get("new") == 'def assetVersion = "v1.5.1"'
                        for operation in profile["operations"]
                    )
                )

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
