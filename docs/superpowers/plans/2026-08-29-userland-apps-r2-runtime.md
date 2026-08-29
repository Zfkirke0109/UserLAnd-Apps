# UserLAnd Apps r2 Runtime Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce ten same-key upgradeable APKs that remain alive on Android 16, expose a usable UserLAnd screen, request only feature-appropriate access, and report `versionName=2026.08.29-r2`.

**Architecture:** Keep the ten launcher snapshots and the reproducible shared UserLAnd dependency boundary. Refresh the one stale launcher snapshot, move FoxBox onto the common modern profile, repair navigation/permissions/foreground-service behavior once in that shared profile, and stage the latest small support runtime from four checksum-locked ABI archives. A fixed r2 release contract feeds build, emulator, and release jobs so the exact APKs that survive sustained launch and rc1 upgrade tests are the only APKs eligible for publication.

**Tech Stack:** Android Gradle Plugin 8.7.2, Gradle 8.9, Kotlin 1.7.20 compatibility bridge, Java 17, compile/target SDK 35, Python 3 standard library, Bash, GitHub Actions, Android SDK 35 emulator, `aapt`, `apksigner`, and `adb`.

**Spec:** `docs/superpowers/specs/2026-08-29-userland-apps-r2-runtime-design.md`

## Global Constraints

- Keep the ten package IDs, output filenames, signing secrets, and signing certificate unchanged.
- The visible version is exactly `2026.08.29-r2`; use the fixed monotonic Android version code `2003329000`, which is greater than rc1's `2003324611` and below `2100000000`.
- The release tag is exactly `v2026.08.29-r2` and must point to the commit whose ten APKs passed the r2 emulator matrix.
- Keep `Lily-Rader/UserLAndLibrary@8751d21debb0f336b2437106db46bc708e81b7d3`; do not follow inaccessible `CypherpunkArmory/UserLAndLibrary` gitlinks or floating refs.
- Refresh FoxBox to `7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde`; preserve the other nine current locked launcher SHAs unless a fresh head check resolves a different exact SHA before their import step begins.
- Stage `UserLAnd-Assets-Support v1.5.1` from four ABI archives and verify every SHA-256 before extraction. Gradle must not download support assets.
- Do not embed Debian root filesystems or desktop payloads; they remain first-run upstream downloads.
- Do not add camera permission. Add microphone permission only to Andacious. Request notification and all-files access only in the user-initiated session path.
- Declare the target-35 foreground service as `specialUse` with its matching normal permission and a truthful subtype string.
- Preserve `inspect-deps/` as untracked user/debug material; never add, delete, or modify it.
- Never log, persist, or pass signing secrets outside the existing environment-backed signing boundary.
- No release claim is complete until all ten signed rc1-to-r2 upgrades and sustained launches pass in one clean matrix run.

---

### Task 1: Isolate r2 work and lock one release contract

**Files:**
- Create: `release.lock.json`
- Modify: `sources.lock.json`
- Modify: `tools/validate_contract.py`
- Modify: `tests/test_validate_contract.py`
- Modify: `tests/test_build_contract.py`
- Modify: `scripts/build_app.sh`

**Interfaces:**
- `release.lock.json` produces `release_tag`, `version_name`, and `version_code` for all build/release consumers.
- `validate_contract(root: Path) -> list[str]` rejects a non-r2 name, unsafe version code, wrong tag, stale FoxBox SHA, malformed support-asset metadata, or any app/profile gap.
- `scripts/build_app.sh APP_ID` reads the fixed release version by default; explicit version arguments remain available only for contract fixtures, not release workflows.

- [ ] **Step 1: Create an isolated worktree**

Run:

```bash
git status --short --branch
git worktree add ../UserLAnd-Apps-r2 -b feat/userland-apps-r2 main
```

Expected: the r2 worktree is on `feat/userland-apps-r2`, `inspect-deps/` remains only in the original worktree, and no implementation edit lands on `main`.

- [ ] **Step 2: Write the failing release-lock tests**

Add tests that require:

```python
release = json.loads(Path("release.lock.json").read_text())
self.assertEqual("v2026.08.29-r2", release["release_tag"])
self.assertEqual("2026.08.29-r2", release["version_name"])
self.assertEqual(2003329000, release["version_code"])
self.assertGreater(release["version_code"], 2003324611)
```

Also mutate each value in a temporary root and assert `validate_contract()` returns a targeted error. Assert FoxBox is locked to `7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde`.

- [ ] **Step 3: Run the focused tests and confirm RED**

Run: `python3 -m unittest tests.test_validate_contract tests.test_build_contract -v`

Expected: FAIL because `release.lock.json` is absent and FoxBox still uses the rc1 source SHA.

- [ ] **Step 4: Implement the minimal release contract**

Create:

```json
{
  "schema_version": 1,
  "release_tag": "v2026.08.29-r2",
  "version_name": "2026.08.29-r2",
  "version_code": 2003329000,
  "upgrade_from_tag": "v2026.08.29-rc1",
  "upgrade_from_version_code": 2003324611
}
```

Update FoxBox's exact source ref. Teach the validator to require the release schema and relationships. Make `build_app.sh` read these values when only `APP_ID` is supplied, while retaining validation of explicit fixture arguments.

- [ ] **Step 5: Re-run focused and full contract tests**

Run:

```bash
python3 -m unittest tests.test_validate_contract tests.test_build_contract -v
python3 tools/validate_contract.py
```

Expected: PASS and `Contract valid: 10 apps`.

- [ ] **Step 6: Commit**

```bash
git add release.lock.json sources.lock.json tools/validate_contract.py scripts/build_app.sh tests/test_validate_contract.py tests/test_build_contract.py
git commit -m "build: lock UserLAnd r2 release metadata"
```

### Task 2: Refresh FoxBox and unify all ten modern profiles

**Files:**
- Modify: `apps/foxbox/**`
- Modify: `profiles/foxbox.json`
- Modify: `profiles/modern-shared.json`
- Modify: `tests/test_import_sources.py`
- Modify: `tests/test_apply_compat.py`

**Interfaces:**
- The existing safe importer recreates `apps/foxbox/` only from the exact locked archive and writes the new SHA to `SOURCE.json`.
- `profiles/foxbox.json` extends `modern-shared.json`, uses the current `appVersionName='24.11.27'` anchor, and inserts the same SDK/version contract as the other nine launchers.

- [ ] **Step 1: Write failing source/profile tests**

Require FoxBox's imported `SOURCE.json` to match the new lock, require its profile to inherit modern operations (namespace, Moshi, Kotlin/API bridge), require Java/SDK 35 build anchors, and reject all legacy JDK-11/AGP-4 operations.

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_import_sources tests.test_apply_compat -v`

Expected: FAIL because the vendored FoxBox tree and profile are still rc1-era.

- [ ] **Step 3: Re-import the exact FoxBox snapshot**

Run the existing importer for FoxBox using `sources.lock.json`. Confirm the result excludes `.git`, `.github`, and the broken `UserLAndLibrary` gitlink and includes `SOURCE.json` with the exact resolved SHA.

- [ ] **Step 4: Replace FoxBox's legacy profile with modern inheritance**

Use the same version/API insertion shape as Andacious:

```json
{
  "extends": "modern-shared.json",
  "operations": [
    {
      "type": "insert_after",
      "path": "build.gradle",
      "anchor": "appVersionName='24.11.27'",
      "text": "\ncompileApi=35\ntargetApi=35\nminApi=21\ntoolsVersion='30.0.3'\nversionCode=...\nversionName=...",
      "count": 1
    }
  ]
}
```

Keep `packagingOptions.jniLibs.useLegacyPackaging true` from the refreshed source because the support executables are loaded from `nativeLibraryDir`.

- [ ] **Step 5: Validate every real profile against a fresh locked dependency tree**

Run:

```bash
python3 -m unittest tests.test_import_sources tests.test_apply_compat -v
python3 tools/apply_compat.py --root build/profile-check/foxbox --profile profiles/foxbox.json --check
```

Expected: all focused tests pass and FoxBox reports a valid modern profile without legacy-only operations.

- [ ] **Step 6: Commit**

```bash
git add apps/foxbox profiles/foxbox.json tests/test_import_sources.py tests/test_apply_compat.py
git commit -m "build: refresh FoxBox on the modern launcher baseline"
```

### Task 3: Checksum-lock and stage support assets v1.5.1

**Files:**
- Modify: `dependencies.lock.json`
- Create: `tools/stage_support_assets.py`
- Create: `tests/test_stage_support_assets.py`
- Modify: `scripts/prepare_dependencies.sh`
- Modify: `tools/verify_dependency_tree.py`
- Modify: `tests/test_verify_dependency_tree.py`
- Modify: `tests/test_validate_contract.py`
- Modify: `profiles/modern-shared.json`
- Modify: `tests/test_apply_compat.py`

**Interfaces:**
- `stage_archive(archive: Path, destination: Path, abi: str, release: str) -> list[Path]` safely maps every flat archive member `name` to `app/src/main/jniLibs/<abi>/lib_<name>.so` and writes a provenance marker.
- The dependency restorer cache key is SHA-addressed; a missing, malformed, traversal-bearing, or checksum-mismatched archive stops before Gradle.
- The modern profile changes the historical support version to `v1.5.1`, but staged ABI directories ensure the Gradle download task is already satisfied.

- [ ] **Step 1: Write failing lock, extraction-safety, and tree tests**

Test all four exact ABI records and digests:

```text
arm64-v8a  ec9bb2e652afb0ceab2cc6830809214ee4d786d31ef8463d0ec213aca67ff9ce
armeabi-v7a af0a2667dbf90076fbc4bdde40538db84950bc596aabe24261a766ae57ccfe41
x86         9cb71e2e79fa0d1eb453cf669c8232e0000878a190f5c01f3f17cd01c06ca4d0
x86_64      897e0902202c6c07cb4efd9b0f00f5c33d5d2925092c62b3c14951ba7a371252
```

Build in-memory zip fixtures that prove valid files are renamed deterministically and reject absolute paths, `..`, duplicate destinations, directories, symlinks, and empty archives. Require `verify_dependency_tree()` to find `lib_proot.so`, `lib_busybox.so`, `lib_assets.txt.so`, and the v1.5.1 marker for every ABI.

- [ ] **Step 2: Confirm RED**

Run:

```bash
python3 -m unittest tests.test_validate_contract tests.test_stage_support_assets tests.test_verify_dependency_tree tests.test_apply_compat -v
```

Expected: FAIL because support assets are not locked or staged.

- [ ] **Step 3: Add exact support-asset lock metadata**

Add a `support_assets` object with repository, release, and four entries containing `abi`, immutable GitHub release URL, filename, and 64-character SHA-256. Extend contract validation to require exactly the four supported ABIs and unique URLs/digests.

- [ ] **Step 4: Implement safe deterministic staging**

Use `zipfile.ZipFile`, `PurePosixPath`, and atomic writes. Validate every member before writing any output. Never preserve archive permissions or paths. Write a JSON marker containing release, ABI, archive SHA-256, and staged filenames.

- [ ] **Step 5: Extend the dependency restorer**

For each lock entry, download to `<sha256>-<filename>` using the existing retry/`.part` pattern, run `sha256sum --check` plus `unzip -t`, then call `stage_support_assets.py`. Ensure the cache-hit verifier validates the markers and required binaries. Include all changed restoration files in workflow cache keys.

- [ ] **Step 6: Update the compatibility profile**

Replace the historical support release anchor `v1.3.4` with `v1.5.1` exactly once and add an assertion that Gradle's support-asset task sees all four staged ABI directories. Do not add an unverified fallback URL.

- [ ] **Step 7: Run focused tests and a live clean restoration**

Run:

```bash
python3 -m unittest tests.test_validate_contract tests.test_stage_support_assets tests.test_verify_dependency_tree tests.test_apply_compat -v
tmp_root=$(mktemp -d)
bash scripts/prepare_dependencies.sh dependencies.lock.json "$tmp_root/shared" "$tmp_root/cache"
python3 tools/verify_dependency_tree.py "$tmp_root/shared"
```

Expected: tests pass, four archives verify, all staged binaries are nonempty, and no Gradle task downloads support assets.

- [ ] **Step 8: Commit**

```bash
git add dependencies.lock.json tools/stage_support_assets.py scripts/prepare_dependencies.sh tools/verify_dependency_tree.py profiles/modern-shared.json tests/test_stage_support_assets.py tests/test_verify_dependency_tree.py tests/test_validate_contract.py tests/test_apply_compat.py
git commit -m "build: stage checksummed UserLAnd support assets v1.5.1"
```

### Task 4: Repair shared navigation before inflation

**Files:**
- Modify: `profiles/modern-shared.json`
- Modify: `tests/test_apply_compat.py`

**Interfaces:**
- Every applied modern profile leaves `nav_graph.xml` with `app:startDestination="@id/app_list_fragment"`.
- `MainActivity.setNavStartDestination()` still invokes `graph.setStartDestination(...)` from the stored preference before assigning `navController.graph`.

- [ ] **Step 1: Write the failing real-fixture test**

Copy the locked launcher/shared fixture, apply `profiles/andacious.json`, parse the navigation XML, and assert:

```python
self.assertEqual(
    "@id/app_list_fragment",
    navigation.get("{http://schemas.android.com/apk/res-auto}startDestination"),
)
self.assertIn("graph.setStartDestination", main_activity)
self.assertLess(main_activity.index("graph.setStartDestination"), main_activity.index("navController.graph = graph"))
```

Also assert the old comment claiming no XML destination is removed.

- [ ] **Step 2: Confirm RED with the archived-crash regression**

Run: `python3 -m unittest tests.test_apply_compat.CompatibilityTests.test_modern_navigation_has_valid_inflation_destination -v`

Expected: FAIL because the XML has no start destination.

- [ ] **Step 3: Add one exact shared profile operation**

Replace the navigation root anchor so it contains `app:startDestination="@id/app_list_fragment"`, with `count: 1`. Preserve the existing runtime preference override and its Kotlin API bridge.

- [ ] **Step 4: Apply all ten profiles and verify the generated files**

Run the focused test and each profile's `--check` mode against a clean dependency fixture. Expected: ten valid graphs, all with a nonzero XML destination and runtime override.

- [ ] **Step 5: Commit**

```bash
git add profiles/modern-shared.json tests/test_apply_compat.py
git commit -m "fix: give UserLAnd navigation a valid initial destination"
```

### Task 5: Implement Android 16 permissions and foreground service behavior

**Files:**
- Create: `compat/r2/PermissionHandler.kt`
- Modify: `tools/apply_compat.py`
- Modify: `tests/test_apply_compat.py`
- Modify: `profiles/modern-shared.json`
- Modify: `profiles/andacious.json`
- Modify: all other `profiles/*.json` only where feature-removal assertions differ

**Interfaces:**
- Add compatibility operation `replace_file`, which replaces one target only when its original SHA-256 matches `old_sha256`; if the target already equals the replacement file, it is a no-op.
- `PermissionHandler.permissionsAreGranted(context, forSession)` branches by SDK and build feature flags.
- `PermissionHandler.requestNecessaryPermissions(activity, forSession)` uses the All Files Access settings flow on API 30+, runtime storage on API 23-29, `POST_NOTIFICATIONS` on API 33+ only for session service startup, and microphone only when `USES_MICROPHONE=true`.
- `permissionsWereGranted()` checks the permission/result pairs dynamically and never assumes fixed array indexes.
- `MainActivity` stores the pending user action, rechecks special access from `onResume()`, resumes only after access is granted, and does not loop after denial.

- [ ] **Step 1: Add failing `replace_file` engine tests**

Test exact old-hash replacement, already-applied idempotence, missing source rejection, path-escape rejection, and wrong-old-hash rejection. The operation shape is:

```json
{
  "type": "replace_file",
  "path": "UserLAndLibrary/app/src/main/java/tech/ula/library/utils/PermissionHandler.kt",
  "source": "compat/r2/PermissionHandler.kt",
  "old_sha256": "b4f0cc790ad2faadc8317a67515fd56defd4a3b08b218f80d6f674617ef60400"
}
```

- [ ] **Step 2: Add failing Android permission/profile tests**

Apply the profile to a real shared tree and assert the merged source contract contains:

```kotlin
Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
Environment.isExternalStorageManager()
Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION
Manifest.permission.POST_NOTIFICATIONS
grantResults.indices.all
```

Assert it does not contain `grantResults[1]`, an unconditional legacy storage pair, or a denial callback that immediately reopens the dialog.

Assert the generated manifest:

- removes `<uses-permission tools:node="removeAll"/>`;
- limits `READ_EXTERNAL_STORAGE` and `WRITE_EXTERNAL_STORAGE` to `android:maxSdkVersion="29"`;
- declares all normal permissions from the spec, `MANAGE_EXTERNAL_STORAGE`, and `POST_NOTIFICATIONS`;
- declares `FOREGROUND_SERVICE_SPECIAL_USE`;
- declares `ServerService` with `android:foregroundServiceType="specialUse"` and `android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE`;
- excludes CAMERA for all apps;
- includes RECORD_AUDIO only for Andacious.

- [ ] **Step 3: Confirm RED**

Run: `python3 -m unittest tests.test_apply_compat -v`

Expected: FAIL on the missing operation, legacy handler, stripped manifest, and missing foreground-service type.

- [ ] **Step 4: Implement `replace_file` safely**

Extend `apply_profile(root, profile, assets_root=repository_root)` and the CLI. Resolve replacement sources beneath the repository root, compare SHA-256 values before mutation, write with the target's mode, and preserve `--check` symlink behavior.

- [ ] **Step 5: Implement the r2 permission handler**

Use an explicit list builder:

```kotlin
private fun runtimePermissions(forSession: Boolean): Array<String> {
    val required = mutableListOf<String>()
    if (Build.VERSION.SDK_INT in Build.VERSION_CODES.M..Build.VERSION_CODES.Q) {
        required += Manifest.permission.READ_EXTERNAL_STORAGE
        required += Manifest.permission.WRITE_EXTERNAL_STORAGE
    }
    if (forSession && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        required += Manifest.permission.POST_NOTIFICATIONS
    }
    if (BuildConfig.USES_MICROPHONE) required += Manifest.permission.RECORD_AUDIO
    return required.distinct().toTypedArray()
}
```

Treat `MANAGE_EXTERNAL_STORAGE` as special access, not a runtime permission. Send users to `package:${activity.packageName}` with the app-specific settings action, fall back to the global action when necessary, and recheck in `onResume()`. Keep SAF import/export independent of broad storage access.

- [ ] **Step 6: Patch MainActivity and service startup with exact anchors**

Replace both session/app selection permission gates with the new `forSession=true` flow. Change SAF import/export gates to `forSession=false` or remove storage gating when the document picker is sufficient. Change service startup to the target-compatible foreground-service path and guarantee `startForeground()` is reached promptly.

- [ ] **Step 7: Patch the merged manifest contract**

Use exact shared-profile operations plus app-specific feature assertions. Keep `android:extractNativeLibs="true"`. Add the special-use service property and matching normal permission based on Android's target-34+ foreground-service contract.

- [ ] **Step 8: Run all profile tests and real checks**

Run:

```bash
python3 -m unittest tests.test_apply_compat -v
for app in foxbox andacious gnuplot r libredocs devstudio inkscape birdbox gimp idle; do
  python3 tools/apply_compat.py --root "build/profile-check/$app" --profile "profiles/$app.json" --check
done
```

Expected: every profile passes; only Andacious retains microphone permission; no app requests camera; service declarations are target-35 valid.

- [ ] **Step 9: Commit**

```bash
git add compat/r2/PermissionHandler.kt tools/apply_compat.py profiles tests/test_apply_compat.py
git commit -m "fix: implement Android 16 runtime access contracts"
```

### Task 6: Turn the emulator smoke check into sustained runtime QA

**Files:**
- Modify: `scripts/emulator_smoke.sh`
- Modify: `tests/test_emulator_contract.py`
- Modify: `.github/workflows/upgrade-smoke.yml`
- Modify: `tests/test_workflow_contract.py`

**Interfaces:**
- `emulator_smoke.sh PACKAGE_ID OLD_APK NEW_APK EVIDENCE_DIR EXPECTED_VERSION_NAME` upgrades first, then performs a clean cold launch and a minimum 20-second stability window.
- The script fails on dead PID, wrong foreground activity, crash-buffer output, app-scoped fatal exception, ANR/force-finish, missing UI content, wrong version, wrong permission contract, or signature-incompatible upgrade.
- Evidence is captured by the EXIT trap regardless of success.

- [ ] **Step 1: Write failing smoke-script contract tests**

Require the script to contain or invoke checks for:

```text
adb shell am force-stop
adb shell am start -W
adb shell pidof
adb shell dumpsys activity activities
adb logcat -b crash
adb shell uiautomator dump
adb exec-out screencap -p
versionName=2026.08.29-r2
20-second conditional stability loop
```

Require upgrade to complete before logcat clear/cold launch. Assert the old monkey-only sequence is absent.

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_emulator_contract tests.test_workflow_contract -v`

Expected: FAIL because rc1's script does not test process stability, crash buffers, UI, or r2 permissions.

- [ ] **Step 3: Implement evidence-first shell helpers**

Add `capture_evidence`, `fail`, `wait_for_activity`, `assert_process_stable`, `assert_no_crash`, `assert_ui_content`, and `assert_permissions`. Capture full/logcat crash buffers, `dumpsys activity`, `dumpsys package`, `dumpsys window`, UI XML, screenshot, resolved launcher, PID samples, version/certificate output, and merged permissions.

Use conditional polling with short intervals; do not use one blind 20-second sleep. Scope fatal-exception checks to the package/PID and still fail on system records naming the package.

- [ ] **Step 4: Exercise Android 16 permission behavior**

On API 35:

- verify legacy READ/WRITE are not runtime requirements;
- verify CAMERA is absent;
- verify RECORD_AUDIO is requested only for Andacious;
- use `appops` to start with all-files access denied, trigger a session access path, confirm the special-settings handoff, grant it for the test, return to the app, and require the pending action to resume without a denial loop;
- deny notifications initially and confirm the first screen remains stable; then grant notifications before session service validation.

- [ ] **Step 5: Use the exact rc1 release APK for upgrade**

Change the workflow to download `v2026.08.29-rc1/<output_name>` as `old.apk`, verify its published SHA from `SHA256SUMS`, build r2 once from `release.lock.json`, and install with `adb install -r`. Do not build a synthetic old version from current source.

- [ ] **Step 6: Re-run contract tests and shell parsing**

Run:

```bash
python3 -m unittest tests.test_emulator_contract tests.test_workflow_contract -v
bash -n scripts/emulator_smoke.sh
python3 - <<'PY'
import yaml
for path in ('.github/workflows/upgrade-smoke.yml',):
    yaml.safe_load(open(path, encoding='utf-8'))
PY
```

Expected: all focused tests pass and workflow YAML parses.

- [ ] **Step 7: Commit**

```bash
git add scripts/emulator_smoke.sh .github/workflows/upgrade-smoke.yml tests/test_emulator_contract.py tests/test_workflow_contract.py
git commit -m "test: require sustained UserLAnd launch and permission evidence"
```

### Task 7: Make build/release metadata describe the exact r2 inputs

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `.github/workflows/upgrade-smoke.yml`
- Modify: `tools/release_manifest.py`
- Modify: `tests/test_release_manifest.py`
- Modify: `tests/test_workflow_contract.py`
- Modify: `README.md`

**Interfaces:**
- All workflows read `release.lock.json`; none derive version codes from run IDs or workflow-local counters.
- `build_manifest(dist, sources_lock, dependencies_lock, release_lock, generated_at) -> dict` requires exact r2 version name/code/tag and records shared library/support-asset provenance.
- Release publication is non-draft and non-prerelease only after all ten sustained emulator jobs pass at the same commit.

- [ ] **Step 1: Write failing metadata/workflow tests**

Require every APK to equal the release lock's version name/code, all version names to end with `r2`, certificate to match, and manifest top-level data to include:

```json
{
  "shared_dependency": {
    "repository": "Lily-Rader/UserLAndLibrary",
    "ref": "8751d21debb0f336b2437106db46bc708e81b7d3"
  },
  "support_assets": {
    "release": "v1.5.1",
    "archives": [
      {"abi": "arm64-v8a", "sha256": "ec9bb2e652afb0ceab2cc6830809214ee4d786d31ef8463d0ec213aca67ff9ce"},
      {"abi": "armeabi-v7a", "sha256": "af0a2667dbf90076fbc4bdde40538db84950bc596aabe24261a766ae57ccfe41"},
      {"abi": "x86", "sha256": "9cb71e2e79fa0d1eb453cf669c8232e0000878a190f5c01f3f17cd01c06ca4d0"},
      {"abi": "x86_64", "sha256": "897e0902202c6c07cb4efd9b0f00f5c33d5d2925092c62b3c14951ba7a371252"}
    ]
  }
}
```

Require workflows to use Java 17 for all apps, the fixed r2 code/name, the r2 tag, strengthened emulator script, artifact/evidence aggregate gates, and no `--prerelease` flag.

- [ ] **Step 2: Confirm RED**

Run: `python3 -m unittest tests.test_release_manifest tests.test_workflow_contract -v`

Expected: FAIL because rc1/run-derived metadata remains.

- [ ] **Step 3: Implement exact manifest validation**

Pass all three lock paths to `release_manifest.py`. Reject an APK even when its package/certificate are valid if its name/code differ from r2. Include source SHA per app and locked shared/support provenance at top level. Keep deterministic ordering and `SHA256SUMS`.

- [ ] **Step 4: Unify workflow build inputs**

Make CI build exactly ten signed r2 APKs with Java 17. Include support-staging files in dependency cache keys. Make release publication depend on a successful ten-entry sustained-launch matrix plus an aggregate job that finds exactly ten APKs and ten nonempty evidence bundles.

- [ ] **Step 5: Update README without claiming unearned verification**

Document r2's runtime fixes, exact permissions and why they are requested, support runtime v1.5.1, first-run external payload behavior, upgrade path, and a `Pending r2 verification` status until remote evidence passes.

- [ ] **Step 6: Run focused/full tests and parse every workflow**

Run:

```bash
python3 -m unittest tests.test_release_manifest tests.test_workflow_contract -v
python3 -m unittest discover -s tests -v
python3 tools/validate_contract.py
python3 - <<'PY'
import yaml
from pathlib import Path
for path in Path('.github/workflows').glob('*.yml'):
    yaml.safe_load(path.read_text(encoding='utf-8'))
PY
```

Expected: all tests, contract validation, and workflow parsing pass.

- [ ] **Step 7: Commit**

```bash
git add release.lock.json .github/workflows tools/release_manifest.py tests/test_release_manifest.py tests/test_workflow_contract.py README.md
git commit -m "release: gate UserLAnd r2 on verified runtime evidence"
```

### Task 8: Build, review, publish, and verify r2

**Files:**
- Modify only evidence-backed files revealed by the verification loop.
- Modify: `README.md` after remote verification.

**Interfaces:**
- A review compares implementation to every spec acceptance criterion.
- GitHub Actions produces exactly ten signed r2 APKs, ten complete sustained-launch evidence artifacts, `SHA256SUMS`, and `release-manifest.json` from one commit.

- [ ] **Step 1: Run the clean local verification suite**

Run:

```bash
git status --short
python3 -m unittest discover -s tests -v
python3 tools/validate_contract.py
bash -n scripts/*.sh
for workflow in .github/workflows/*.yml; do python3 -c 'import sys,yaml; yaml.safe_load(open(sys.argv[1]))' "$workflow"; done
```

Expected: clean intentional diff, all tests pass, contract valid, all shell/YAML parses.

- [ ] **Step 2: Perform a clean locked dependency/profile/build check**

Restore dependencies into a new temporary directory, validate all ten profiles against it, and build at least one modern launcher plus FoxBox locally when Android SDK/signing inputs are available. If local SDK/signing inputs are unavailable, record that limitation and rely on the clean GitHub runners; never substitute a false local success.

- [ ] **Step 3: Request code review and resolve findings**

Review source locking, archive extraction safety, Kotlin/API behavior, permission minimization, foreground-service compliance, smoke-test false-positive risks, workflow release ordering, and secret handling. Add a failing regression test before every accepted behavior fix.

- [ ] **Step 4: Publish the feature branch and open a PR**

```bash
git push -u origin feat/userland-apps-r2
```

Open a PR titled `Fix Android 16 runtime and release UserLAnd Apps r2`. Require repository contracts and all ten signed build jobs to pass before merge.

- [ ] **Step 5: Inspect real PR logs and fix only evidenced failures**

For each failing matrix entry, capture the first root-cause compiler/runtime record, determine whether it is shared or app-specific, write the smallest failing regression, patch the appropriate profile/tool, rerun the full local suite, commit, and wait for the fresh matrix. Do not make speculative dependency upgrades while a deterministic failure is still unresolved.

- [ ] **Step 6: Merge with the explicit release trigger**

Merge only after the PR contract and ten signed APK jobs are green. Use the exact merge/commit title expected by the guarded r2 workflow so the ten emulator jobs and release job run once on `main`.

- [ ] **Step 7: Require one clean ten-app emulator matrix**

For every app, verify:

- exact package ID, version name `2026.08.29-r2`, version code `2003329000`, and certificate;
- rc1 installation and in-place r2 update;
- launcher resolution and `tech.ula.library.MainActivity` foreground state;
- PID survival for at least 20 seconds;
- nonempty visible UI hierarchy;
- no app fatal exception, ANR, force-finish, or process death;
- Android 16 permission contract and All Files Access resume behavior;
- complete uploaded evidence bundle.

- [ ] **Step 8: Verify the published release object**

Require tag `v2026.08.29-r2` to point to the verified commit and contain exactly ten APKs plus `SHA256SUMS` and `release-manifest.json`. Verify every asset checksum, manifest provenance, certificate, package, version name, and version code.

- [ ] **Step 9: Update status to Verified and rerun current-main CI**

Change README's r2 status only after Step 8. The docs-only commit must skip the expensive guarded emulator matrix but still pass the standard ten-APK build/aggregate workflow on current `main`.

- [ ] **Step 10: Final device handoff**

Provide the r2 release URL, per-app APK filters for Obtainium, permission rationale, support runtime version, and exact S23 Ultra test steps. State plainly that the desktop/rootfs payloads still download on first use and that on-device first-session evidence from the user's Android 16 phone is the final hardware confirmation.
