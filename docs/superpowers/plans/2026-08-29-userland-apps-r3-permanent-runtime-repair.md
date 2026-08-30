# UserLAnd Apps r3 Permanent Runtime Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship ten signed r3 APKs that reliably download, verify, extract, repair, and launch their Linux applications while crediting and linking to the official paid Google Play apps.

**Architecture:** Replace the OEM DownloadManager boundary with a persisted app-owned foreground service, project an immutable per-package/per-ABI payload catalog into every APK, adapt the old launcher runtime to support-assets v1.5.1 with static BusyBox extraction, and rehydrate session state after recreation. Gate release on real clean first-run payload downloads and session readiness on API 35 and API 36.

**Tech Stack:** Python 3 repository tooling/tests, Bash/GitHub Actions, Android/Kotlin, OkHttp 4.9, coroutines 1.4, Room 2.3, Robolectric/JUnit, Android emulator/adb.

**Spec:** `docs/superpowers/specs/2026-08-29-userland-apps-r3-permanent-runtime-design.md`

## Global Constraints

- Release tag is `v2026.08.29-r3`, version name is `2026.08.29-r3`, and version code is `2003329001`.
- Upgrade source is public `v2026.08.29-r2`, version code `2003329000`, with the same signing identity.
- Keep support assets v1.5.1 and adapt the retained library; do not silently roll back to v1.3.4.
- Do not use Android DownloadManager for setup payloads.
- Never write extraction success until verified filesystem anchors and user creation exist.
- Preserve valid existing filesystems and unrelated user-home data during r2 repair.
- Every default payload is selected by exact release data and SHA-256, never `latest` at runtime.
- Minimum necessary permissions remain unchanged except the explicit `dataSync` foreground-service permission/type.
- Creator support appears once after successful setup and remains permanently available through **About & Support**.
- Work inline in `feat/userland-apps-r3`; do not dispatch subagents.

---

## File Structure

### Repository contracts and generation

- `release.lock.json` — the single r3 version and upgrade contract.
- `payloads.lock.json` — exact package/ABI/release/asset/digest catalog.
- `credits.lock.json` — official Google Play badge provenance and package URLs.
- `tools/payload_lock.py` — discover, download, hash, aggregate, and verify payload records.
- `tools/render_runtime_catalog.py` — deterministic projection from `payloads.lock.json` to the bundled runtime JSON.
- `tools/verify_dependency_tree.py` — complete support-file, marker, and ELF dependency verification.
- `tools/apply_compat.py` — safe `copy_file` support for new r3 overlay files.
- `.github/workflows/payload-lock.yml` — one job per launcher/ABI plus deterministic aggregation.

### Android compatibility overlay

- `compat/r3/java/tech/ula/library/model/repositories/LockedPayloadCatalog.kt` — package/ABI lookup and catalog parsing.
- `compat/r3/java/tech/ula/library/utils/DownloadJournal.kt` — durable batch and item state.
- `compat/r3/java/tech/ula/library/utils/ResumableAssetTransfer.kt` — Range-aware atomic OkHttp transfer and digest verification.
- `compat/r3/java/tech/ula/library/AssetDownloadService.kt` — `dataSync` foreground-service lifecycle and notification.
- `compat/r3/java/tech/ula/library/utils/AssetDownloader.kt` — state-machine adapter over the service journal.
- `compat/r3/java/tech/ula/library/utils/BusyboxExecutor.kt` — static host tool and complete dynamic environment.
- `compat/r3/java/tech/ula/library/utils/FilesystemManager.kt` — safe extraction, anchor verification, and r2 repair.
- `compat/r3/java/tech/ula/library/utils/CreatorSupportPrompter.kt` — one-time and menu-invoked support card plus store intents.
- `compat/r3/res/layout/dia_creator_support.xml` — app icon, creator text, and Play badge.
- `compat/r3/res/drawable-nodpi/google_play_badge.png` — official local badge.
- `compat/r3/assets/r3-payloads.json` — generated runtime catalog.
- `compat/r3/test/...` — Android unit tests copied into the restored shared library.

### Existing sources patched by profile

- `profiles/modern-shared.json` — append exact-hash replacements, new overlay copies, manifest/service, menu, strings, and Gradle test dependencies.
- `UserLAndLibrary/.../MainActivity.kt` — custom local download events and creator-support entry points.
- `UserLAndLibrary/.../SessionStartupFsm.kt` — persisted session rehydration and safe download re-entry.
- `UserLAndLibrary/.../MainActivityViewModel.kt` — progress/error/retry states without losing selections.
- `UserLAndLibrary/.../AssetRepository.kt` — immutable catalog selection.
- `UserLAndLibrary/app/src/main/AndroidManifest.xml` — `dataSync` service declaration.
- `UserLAndLibrary/app/src/main/res/menu/menu_options.xml` — **About & Support** item.
- `UserLAndLibrary/app/src/main/res/values/strings.xml` — progress, repair, and creator copy.

### Verification and release

- `scripts/emulator_smoke.sh` — r2 upgrade plus clean first-run setup, real payloads, extraction, session readiness, relaunch, and evidence.
- `.github/workflows/upgrade-smoke.yml` — ten apps on API 35 and API 36, artifact aggregation, release gate.
- `tools/release_manifest.py` — r3 payload-lock and evidence provenance.
- `README.md` — r3 status and official purchase-credit disclosure after release.

---

### Task 1: r3 Contract and Safe Overlay Creation

**Files:**
- Modify: `tests/test_apply_compat.py`
- Modify: `tools/apply_compat.py`
- Modify: `tests/test_validate_contract.py`
- Modify: `tests/test_build_contract.py`
- Modify: `release.lock.json`
- Modify: `tools/validate_contract.py`

**Interfaces:**
- Produces: profile operation `{"type":"copy_file","source":str,"path":str,"sha256":str}`.
- Produces: exact r3 version values consumed by builds, manifests, workflows, and release tooling.

- [ ] **Step 1: Write failing behavior tests for `copy_file`**

```python
def test_copy_file_creates_exact_asset_and_is_idempotent(self):
    # A hand-written source is copied once, its literal bytes are asserted,
    # and a second profile application reports no change.

def test_copy_file_rejects_source_or_destination_escape(self):
    # `../outside` in either field raises ValueError before a write.

def test_copy_file_rejects_conflicting_existing_target(self):
    # Existing different bytes are never overwritten by a create operation.
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python3 -m unittest tests.test_apply_compat.CompatibilityTests.test_copy_file_creates_exact_asset_and_is_idempotent tests.test_apply_compat.CompatibilityTests.test_copy_file_rejects_source_or_destination_escape tests.test_apply_compat.CompatibilityTests.test_copy_file_rejects_conflicting_existing_target -v`

Expected: failures because `copy_file` is unsupported.

- [ ] **Step 3: Implement minimal safe copy semantics**

```python
elif operation_type == "copy_file":
    source = resolve_bounded(assets_root, operation["source"], "asset")
    target = resolve_bounded(root, operation["path"], "target")
    expected = operation["sha256"]
    if sha256_bytes(source.read_bytes()) != expected:
        raise ValueError("copy_file source SHA-256 mismatch")
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise ValueError("copy_file target already exists with different bytes")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        changed.append(operation["path"])
```

- [ ] **Step 4: Run focused and full repository tests**

Run: `python3 -m unittest tests.test_apply_compat -v`

Run: `python3 -m unittest discover -v`

Expected: all tests pass.

- [ ] **Step 5: Write failing r3 release-contract tests**

```python
def test_r3_release_contract_is_exact_and_monotonic(self):
    lock = json.loads(Path("release.lock.json").read_text())
    self.assertEqual("v2026.08.29-r3", lock["release_tag"])
    self.assertEqual("2026.08.29-r3", lock["version_name"])
    self.assertEqual(2003329001, lock["version_code"])
    self.assertEqual("v2026.08.29-r2", lock["upgrade_from_tag"])
    self.assertEqual(2003329000, lock["upgrade_from_version_code"])
```

- [ ] **Step 6: Run the release-contract tests and confirm RED**

Run: `python3 -m unittest tests.test_validate_contract tests.test_build_contract -v`

Expected: r2 values differ from the r3 literals.

- [ ] **Step 7: Update the lock and r3 validators minimally**

Set the five exact values from the test and update messages/regexes that are explicitly version-bound. Do not change signing identity or source locks.

- [ ] **Step 8: Verify and commit Task 1**

Run: `python3 -m unittest discover -v`

Run: `python3 tools/validate_contract.py`

Commit: `git commit -am "build: establish r3 overlay and release contract"`

---

### Task 2: Immutable Payload Lock and Runtime Projection

**Files:**
- Create: `payloads.lock.json`
- Create: `tools/payload_lock.py`
- Create: `tools/render_runtime_catalog.py`
- Create: `tests/test_payload_lock.py`
- Create: `tests/test_runtime_catalog.py`
- Create: `.github/workflows/payload-lock.yml`
- Create: `compat/r3/assets/r3-payloads.json`

**Interfaces:**
- Produces: `verify_payload_lock(path: Path) -> list[str]`.
- Produces: runtime lookup keys `(package_id, abi, filename)` with `release`, `url`, `size`, `sha256`, and `asset_list`.
- Consumes: the ten package records from `sources.lock.json` and fixed repositories/releases from the approved spec.

- [ ] **Step 1: Write RED tests with a complete two-app fixture**

```python
def test_lock_rejects_latest_missing_digest_and_missing_abi(self):
    errors = verify_payload_lock(self.fixture_with(release="latest", sha256="", omit_abi="x86"))
    self.assertIn("mutable release selector", "\n".join(errors))
    self.assertIn("missing SHA-256", "\n".join(errors))
    self.assertIn("missing ABI x86", "\n".join(errors))

def test_runtime_projection_is_sorted_and_lossless(self):
    rendered = render_catalog(self.complete_fixture())
    self.assertEqual(["tech.ula.andacious", "tech.ula.foxbox_pro"], [x["package_id"] for x in rendered["apps"]])
    self.assertEqual("a" * 64, rendered["apps"][0]["abis"]["arm64"]["assets.tar.gz"]["sha256"])
```

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_payload_lock tests.test_runtime_catalog -v`

Expected: import failures because the tools do not exist.

- [ ] **Step 3: Implement schema validation and deterministic projection**

The validator must require exactly ten source-lock package IDs and every
upstream-supported ABI: `arm64`, `arm`, `x86`, and `x86_64` for nine apps, and
`arm64`, `arm`, and `x86_64` for deVStudio because its releases contain no x86
assets. It must require exactly `assets.tar.gz` and `rootfs.tar.gz`, a positive
release asset ID/size, a 64-lowercase-hex digest,
an HTTPS GitHub release URL containing the fixed tag, and a nonempty literal
asset list. Render with sorted keys, two-space indentation, and a trailing
newline.

- [ ] **Step 4: Verify GREEN**

Run: `python3 -m unittest tests.test_payload_lock tests.test_runtime_catalog -v`

Expected: all focused tests pass.

- [ ] **Step 5: Add the payload-hash matrix workflow**

Each supported launcher/ABI job (39 total) resolves its exact tag, downloads the three named release
assets, verifies the API-reported byte length, computes SHA-256 while streaming,
parses the literal assets list, and uploads one JSON record. Aggregation calls:

```bash
python3 tools/payload_lock.py aggregate \
  --sources sources.lock.json \
  --records payload-records \
  --output payloads.lock.json
python3 tools/payload_lock.py verify payloads.lock.json
python3 tools/render_runtime_catalog.py \
  payloads.lock.json compat/r3/assets/r3-payloads.json
```

- [ ] **Step 6: Run the one-time workflow and retain its exact artifacts**

Push only the tool/tests/workflow checkpoint to the feature branch, run
`payload-lock.yml`, download all 40 record artifacts plus the aggregate, and
copy the verified aggregate and runtime projection into the two declared paths.

- [ ] **Step 7: Reverify generated bytes and commit Task 2**

Run: `python3 tools/payload_lock.py verify payloads.lock.json`

Run: `python3 tools/render_runtime_catalog.py --check payloads.lock.json compat/r3/assets/r3-payloads.json`

Run: `python3 -m unittest discover -v`

Commit: `git commit -am "build: lock exact first-run payloads"`

---

### Task 3: Complete v1.5.1 Support and BusyBox Contract

**Files:**
- Modify: `tests/test_verify_dependency_tree.py`
- Modify: `tools/verify_dependency_tree.py`
- Modify: `tests/test_stage_support_assets.py`
- Modify: `tools/stage_support_assets.py`
- Create: `compat/r3/java/tech/ula/library/utils/BusyboxExecutor.kt`
- Create: `compat/r3/test/tech/ula/library/utils/R3BusyboxExecutorTest.kt`
- Modify: `profiles/modern-shared.json`

**Interfaces:**
- Produces: `elf_needed(path: Path) -> tuple[str, ...]` in repository tooling.
- Produces: `BusyboxWrapper.hostBusybox: File`, preferring `busybox_static`.
- Produces: `runHostApplet(applet: String, args: List<String>, listener) -> ExecutionResult` without shell interpolation.

- [ ] **Step 1: Write RED repository tests for the omitted v1.5.1 contract**

```python
def test_v151_requires_static_busybox_companion_and_extraction_scripts(self):
    for name in ("lib_busybox_static.so", "lib_libbusybox.so.1.37.0.so", "lib_extractFilesystem.sh.so", "lib_addNonRootUser.sh.so"):
        self.assertIn(name, SUPPORT_FILES)

def test_marker_file_list_must_equal_staged_directory(self):
    # Add an unrecorded staged file and assert verification reports it.

def test_missing_needed_library_is_reported(self):
    # Feed a literal readelf fixture needing libbusybox.so.1.37.0 and an empty staged set.
```

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_verify_dependency_tree tests.test_stage_support_assets -v`

Expected: omitted files and ELF closure are not enforced.

- [ ] **Step 3: Implement complete marker and ELF validation**

Parse `readelf -d` output into literal `NEEDED` names. Resolve Android system
libraries through a fixed allowlist and staged companions through Android's
`lib_<name>.so` packaging transformation. Verify every marker digest, release,
ABI, and sorted file list exactly.

- [ ] **Step 4: Verify the real restored four-ABI tree**

Run: `python3 tools/verify_dependency_tree.py build/r3-shared`

Expected: `Dependency tree verified` only after all v1.5.1 files and closure are present.

- [ ] **Step 5: Write and run RED Android BusyBox behavior tests**

```kotlin
@Test fun hostCommandsPreferStaticBusybox() {
    assertEquals(files.busyboxStatic, wrapper.hostBusybox)
}

@Test fun everyBusyboxEnvironmentContainsSupportLibraryPath() {
    assertEquals(files.supportDir.absolutePath, wrapper.getBusyboxEnv()["LD_LIBRARY_PATH"])
}

@Test fun hostAppletKeepsArgumentsSeparate() {
    assertEquals(listOf(files.busyboxStatic.path, "tar", "-tzf", "name with space.tar.gz"), wrapper.wrapHostApplet("tar", listOf("-tzf", "name with space.tar.gz")))
}
```

Apply the overlay to an Andacious fixture and run
`:UserLAndLibrary:app:testDebugUnitTest`; confirm failures against the old
executor.

- [ ] **Step 6: Implement the minimal static-host executor and profile replacement**

Keep proot behavior intact, add `LD_LIBRARY_PATH` to basic execution, and route
host applets through static BusyBox with argument lists.

- [ ] **Step 7: Verify and commit Task 3**

Run the focused Android tests, all Python tests, dependency verification, and all ten profile dry-runs.

Commit: `git commit -am "fix: restore v151 busybox runtime contract"`

---

### Task 4: Safe Extraction and Damaged-r2 Migration

**Files:**
- Create: `compat/r3/java/tech/ula/library/utils/FilesystemManager.kt`
- Create: `compat/r3/test/tech/ula/library/utils/R3FilesystemManagerTest.kt`
- Modify: `profiles/modern-shared.json`

**Interfaces:**
- Produces: `validateRootfsArchive(archive: File) -> ExecutionResult`.
- Produces: `hasUsableFilesystem(target: String, username: String? = null) -> Boolean`.
- Preserves: `extractFilesystem(filesystem, listener) -> ExecutionResult` call signature.

- [ ] **Step 1: Write RED tests reproducing BirdBox and damaged r2**

```kotlin
@Test fun successMarkerWithoutShellIsNotSuccessful() {
    fixture.successMarker.createNewFile()
    assertFalse(manager.hasFilesystemBeenSuccessfullyExtracted(fixture.id))
}

@Test fun traversalMemberFailsBeforeExtraction() {
    executor.archiveEntries = listOf("etc/passwd", "../../escape")
    assertTrue(manager.extractFilesystem(filesystem, {}).let { it is FailedExecution })
    assertFalse(fixture.successMarker.exists())
}

@Test fun userCreationFailureCannotWriteSuccess() {
    executor.extractionResult = SuccessfulExecution
    executor.prootResult = FailedExecution("useradd failed")
    assertTrue(manager.extractFilesystem(filesystem, {}).let { it is FailedExecution })
    assertFalse(fixture.successMarker.exists())
}

@Test fun repairPreservesExistingHomeFile() {
    fixture.userFile.writeText("keep")
    manager.extractFilesystem(filesystem, {})
    assertEquals("keep", fixture.userFile.readText())
}
```

- [ ] **Step 2: Confirm RED against the applied r2 source**

Run the focused Gradle test and confirm the false marker is currently accepted.

- [ ] **Step 3: Implement safe list/extract/user/verify ordering**

Use separate static BusyBox argument lists. Reject an archive member when:

```kotlin
val unsafe = path.startsWith("/") || path.split('/').any { it == ".." } || path.isBlank()
```

Remove stale success before work. Extract without deleting existing unrelated
home content, run `addNonRootUser.sh` through proot, verify `/bin/sh`,
`/etc/passwd`, `/home/<username>`, and required support files, then atomically
replace failure with success. On any error retain the rootfs archive for Retry.

- [ ] **Step 4: Verify GREEN and mutation behavior**

Run focused tests, then temporarily return `success.exists()` from the success
predicate and prove `successMarkerWithoutShellIsNotSuccessful` fails; restore
the implementation and rerun green.

- [ ] **Step 5: Apply all ten profiles and commit Task 4**

Run all profile checks plus representative Andacious and BirdBox Gradle unit tests.

Commit: `git commit -am "fix: extract and repair filesystems safely"`

---

### Task 5: Resumable Foreground Downloads and State Rehydration

**Files:**
- Create: `compat/r3/java/tech/ula/library/utils/DownloadJournal.kt`
- Create: `compat/r3/java/tech/ula/library/utils/ResumableAssetTransfer.kt`
- Create: `compat/r3/java/tech/ula/library/AssetDownloadService.kt`
- Create: `compat/r3/java/tech/ula/library/utils/AssetDownloader.kt`
- Create: `compat/r3/java/tech/ula/library/model/repositories/LockedPayloadCatalog.kt`
- Create: `compat/r3/java/tech/ula/library/model/repositories/AssetRepository.kt`
- Create: `compat/r3/test/tech/ula/library/utils/R3ResumableAssetTransferTest.kt`
- Create: `compat/r3/test/tech/ula/library/utils/R3DownloadJournalTest.kt`
- Create: `compat/r3/test/tech/ula/library/model/state/R3SessionDownloadRecoveryTest.kt`
- Modify: `profiles/modern-shared.json`

**Interfaces:**
- `DownloadItem(id, url, destination, expectedBytes, sha256, bytesWritten, attempts, state, error)`.
- `DownloadBatch(sessionId, filesystemId, items, state)`.
- `ResumableAssetTransfer.transfer(item, onProgress) -> TransferResult`.
- `AssetDownloadService.enqueue(context, batchId)` and local action `tech.ula.library.DOWNLOAD_STATE`.
- `AssetDownloader.syncStateWithCache() -> AssetDownloadState` rehydrates selection context.

- [ ] **Step 1: Write RED MockWebServer transfer tests**

```kotlin
@Test fun resumesPartFileWithRangeAndPublishesAtomically() { /* expect Range bytes=4-, 206, exact final bytes, no .part */ }
@Test fun serverIgnoringRangeRestartsWithoutDuplicatingBytes() { /* 200 after Range produces one exact file */ }
@Test fun checksumMismatchDeletesPublishAndReturnsTerminalFailure() { /* literal wrong digest */ }
@Test fun retriesStopAfterFiveAttempts() { /* six queued 503s, exactly five requests */ }
@Test fun interruptedJournalReloadKeepsSessionAndFilesystemIds() { /* recreate real SharedPreferences-backed journal */ }
```

- [ ] **Step 2: Confirm RED**

Run the focused Gradle tests; expected imports/classes are absent.

- [ ] **Step 3: Implement transfer and journal only**

Use OkHttp timeouts, a `Range` header for nonzero parts, append only on `206`,
restart on `200`, compare expected length, stream SHA-256, fsync, and rename.
Persist state before and after every network boundary. Verify the focused tests
turn green before adding the Android service.

- [ ] **Step 4: Write RED service/state tests**

Test that the service enters foreground before transfer, emits durable terminal
states, stops its notification, and that `SyncDownloadState` reloads the Room
session/filesystem before success or progress is emitted. Assert selecting the
same active session reattaches rather than producing `IncorrectSessionTransition`.

- [ ] **Step 5: Implement the service and state-machine integration**

Declare:

```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" />
<service
    android:name=".AssetDownloadService"
    android:exported="false"
    android:foregroundServiceType="dataSync" />
```

Remove DownloadManager construction, receiver registration, broadcast imports,
and `USE_DOWNLOAD_MANAGER` branching. Use LocalBroadcastManager for same-process
progress/completion signals and journal sync for missed broadcasts.

- [ ] **Step 6: Integrate the locked payload catalog**

Default setup reads `r3-payloads.json` by `packageName` and architecture,
returns bundled `assets.txt`, and adds digest/size to `DownloadMetadata`.
Custom filesystem mode remains network-derived and is marked unlocked for
archive validation.

- [ ] **Step 7: Verify all downloader/state tests and compile all ten APKs**

Run focused Gradle tests, full Python tests, ten profile applications, and ten
`:app:assembleRelease` builds with temporary test signing.

- [ ] **Step 8: Commit Task 5**

Commit: `git commit -am "fix: own and resume first-run downloads"`

---

### Task 6: Actionable Retry/Repair UI and Notification Lifecycle

**Files:**
- Create: `compat/r3/test/tech/ula/library/viewmodel/R3DownloadUiStateTest.kt`
- Create: `compat/r3/java/tech/ula/library/viewmodel/MainActivityViewModel.kt`
- Create: `compat/r3/java/tech/ula/library/model/state/SessionStartupFsm.kt`
- Modify through exact operations: `UserLAndLibrary/.../MainActivity.kt`
- Modify through exact operations: `UserLAndLibrary/.../strings.xml`
- Modify: `profiles/modern-shared.json`

**Interfaces:**
- Produces: byte-aware `DownloadProgress(completedFiles, totalFiles, bytesWritten, totalBytes)`.
- Produces: `DownloadRetryRequired(stage, safeMessage, canRepair)`.
- Produces: `retryDownloads()` and `repairFilesystem()` user actions.

- [ ] **Step 1: Write RED state behavior tests**

Assert literal progress values, terminal download failure without a generic
GitHub message, notification stop on terminal failure, Retry preserving the
batch, Repair invalidating only extraction markers, and a relaunch with a
completed batch continuing through copy/extraction once.

- [ ] **Step 2: Confirm RED**

Run the new focused Gradle test; expected r3 states and actions are absent.

- [ ] **Step 3: Implement minimal states and dialogs**

Progress uses journal bytes. Retry resubmits only incomplete items. Repair
calls the filesystem manager's bounded invalidation. Cancel leaves downloaded
verified payloads available and returns to input. No dialog deletes a valid
filesystem or user home.

- [ ] **Step 4: Verify GREEN, relaunch tests, and activity compilation**

Run focused tests plus all existing `MainActivityViewModelTest` and
`SessionStartupFsmTest` cases, then assemble Andacious, GIMP, and BirdBox.

- [ ] **Step 5: Commit Task 6**

Commit: `git commit -am "fix: recover setup with retry and repair"`

---

### Task 7: Creator Credit and Official Google Play Support Card

**Files:**
- Create: `credits.lock.json`
- Create: `compat/r3/res/drawable-nodpi/google_play_badge.png`
- Create: `compat/r3/res/layout/dia_creator_support.xml`
- Create: `compat/r3/java/tech/ula/library/utils/CreatorSupportPrompter.kt`
- Create: `compat/r3/test/tech/ula/library/utils/R3CreatorSupportPrompterTest.kt`
- Modify through exact operations: `UserLAndLibrary/.../menu_options.xml`
- Modify through exact operations: `UserLAndLibrary/.../strings.xml`
- Modify through exact operations: `UserLAndLibrary/.../MainActivity.kt`
- Modify: `profiles/modern-shared.json`
- Modify: `tests/test_validate_contract.py`

**Interfaces:**
- `CreatorSupportPrompter.showAfterFirstSuccessfulSession()`.
- `CreatorSupportPrompter.showFromMenu()`.
- `CreatorSupportPrompter.marketUri(packageName)` with HTTPS fallback intent.

- [ ] **Step 1: Write RED credit/link tests**

```kotlin
@Test fun packageProducesOfficialMarketAndWebUris() {
    assertEquals("market://details?id=tech.ula.andacious", links.market("tech.ula.andacious").toString())
    assertEquals("https://play.google.com/store/apps/details?id=tech.ula.andacious", links.web("tech.ula.andacious").toString())
}

@Test fun automaticCardShowsOnceButMenuAlwaysShows() { /* real preferences, two automatic calls and two forced calls */ }
```

Add a repository test requiring all ten source-lock package IDs to map to their
same official Play package and requiring the requested credit sentence.

- [ ] **Step 2: Confirm RED**

Run focused Kotlin and Python tests; the prompter, menu, and asset are absent.

- [ ] **Step 3: Acquire and lock Google's official badge**

Download only
`https://play.google.com/intl/en_us/badges/static/images/badges/en_badge_web_generic.png`,
record its byte length and SHA-256 in `credits.lock.json`, and make the contract
test verify the local binary against that digest.

- [ ] **Step 4: Implement the card and activity hooks**

Use `@mipmap/ic_main_launcher` for the installed app icon. Call the automatic
entry only from the confirmed `sessionActivated` handler after setup succeeds.
Add **About & Support** to the overflow menu and force-show the same card there.
The badge click tries the market URI and catches `ActivityNotFoundException`
to use HTTPS.

- [ ] **Step 5: Verify layout/resources for all ten and commit Task 7**

Run focused tests, `aapt2`/Gradle resource compilation through all ten release
builds, and confirm no app-specific icon was copied or replaced.

Commit: `git commit -am "feat: credit creators and link official apps"`

---

### Task 8: Real First-Run Emulator and Release Gate

**Files:**
- Modify: `tests/test_emulator_contract.py`
- Modify: `scripts/emulator_smoke.sh`
- Modify: `tests/test_workflow_contract.py`
- Modify: `.github/workflows/upgrade-smoke.yml`
- Modify: `tools/release_manifest.py`
- Modify: `tests/test_release_manifest.py`

**Interfaces:**
- Produces per app/API: APK, logcat, crash buffer, UI tree, screenshots,
  journal snapshot, payload digest report, extraction anchors, service state,
  and notification state.
- Release consumes exactly 20 successful app/API evidence bundles and ten APKs
  selected from the final verified matrix.

- [ ] **Step 1: Write RED executable gate tests**

Require the smoke script to clear data for a clean path, start setup from a
UI-tree-derived coordinate, interrupt/restart networking once, wait by
condition rather than fixed download duration, compare payload SHA-256 against
the lock, require filesystem anchors, require session readiness, reject
BusyBox linker errors/false markers/pending `.part` files, relaunch, and verify
the creator card/menu link.

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_emulator_contract tests.test_workflow_contract tests.test_release_manifest -v`

Expected: the r2 activity-only gate lacks the required evidence and API matrix.

- [ ] **Step 3: Implement condition-driven adb verification**

Use UI XML for all taps. Poll journal/log/UI conditions up to the per-app
payload timeout while emitting progress every minute. On rooted emulator builds,
assert:

```bash
test -n "$(adb shell find /data/user/0/$PACKAGE_ID/files -path '*/bin/sh' -type f -print -quit)"
test -z "$(adb shell find /data/user/0/$PACKAGE_ID/files -name '*.part' -print -quit)"
```

For every success marker, require a sibling filesystem `/bin/sh` and
`/etc/passwd`. Require a live session service/remote client and reject target
fatal, ANR, force-finish, BusyBox linker, extraction false-success, and illegal
transition signatures.

- [ ] **Step 4: Expand workflow to API 35 and API 36**

Build each signed APK once, fan out ten apps × two APIs, cache immutable
payloads by lock digest, and require all 20 evidence bundles in the release
job. Never redownload or rebuild a different APK in the release job.

- [ ] **Step 5: Verify workflow syntax and repository contracts**

Run: `python3 -m unittest discover -v`

Run: `python3 tools/validate_contract.py`

Run: `bash -n scripts/*.sh`

Parse every `.github/workflows/*.yml` with the repository YAML checker.

- [ ] **Step 6: Commit Task 8**

Commit: `git commit -am "test: gate r3 on real first-run sessions"`

---

### Task 9: Full Verification, PR, Release, and Documentation

**Files:**
- Modify after verified release: `README.md`
- Modify after verified release: release status/provenance documentation

**Interfaces:**
- Consumes all preceding locks, tests, signed APKs, and evidence.
- Produces public `v2026.08.29-r3` with ten APKs, checksums, manifest, and payload provenance.

- [ ] **Step 1: Run fresh local repository verification**

Run all Python tests, contract validation, dependency verification, shell
syntax, Python compilation, payload-lock verification, runtime-catalog check,
badge digest check, and ten exact profile applications against a newly restored
dependency tree.

- [ ] **Step 2: Build all ten signed-equivalent release APKs locally or in PR CI**

Require package, version name/code, certificate, support files, payload catalog,
creator resources, and manifest service declarations for every APK.

- [ ] **Step 3: Review the complete r2..r3 diff against the specification**

Check for DownloadManager remnants, mutable `latest`, unsafe archive paths,
success-before-verification, unbounded retries, permission expansion, release
bypasses, unrelated source changes, and incorrect Play package IDs.

- [ ] **Step 4: Push the exact verified branch and open one PR**

The PR description must include the per-app diagnosis, r3 architecture,
red/green test evidence, payload-lock provenance, and the fact that release
remains blocked on device workflows.

- [ ] **Step 5: Require all PR builds, then merge with the guarded r3 trigger**

Do not merge on partial matrix success. Follow the first failing compiler or
runtime evidence if any job fails; add a reproducing test before each correction.

- [ ] **Step 6: Require all 20 device evidence bundles and publish r3**

Verify the final tag points at the tested merge commit, the release is neither
draft nor prerelease, all ten APKs are the emulator-tested artifacts, and
`SHA256SUMS`, `release-manifest.json`, and payload-lock provenance are present.

- [ ] **Step 7: Update README from pending to verified and merge docs-only PR**

Link the r3 release, signed-build run, runtime matrix, source/Obtainium filters,
creator support explanation, and device-specific reporting instructions.

- [ ] **Step 8: Perform the completion checklist**

Use `superpowers:verification-before-completion`, then
`superpowers:finishing-a-development-branch`. Report exact commands, counts,
commit/tag, PR/release links, and any residual limitation without inferring
Samsung hardware proof from emulator evidence.
