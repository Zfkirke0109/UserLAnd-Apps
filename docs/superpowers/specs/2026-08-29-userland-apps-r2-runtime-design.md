# UserLAnd Apps r2 Runtime Recovery Design

**Date:** 2026-08-29

**Status:** Approved for implementation

**Repository:** `Zfkirke0109/UserLAnd-Apps`

## Purpose

Release ten signed APKs that launch reliably on Android 16, request only the access each launcher needs, use the latest reproducible launcher sources and bundled UserLAnd support binaries, and upgrade in place from `v2026.08.29-rc1`.

Every APK will have the visible Android `versionName` `2026.08.29-r2`. The release tag will be `v2026.08.29-r2`.

## Evidence and root causes

The `rc1` emulator workflow installed and immediately replaced each launched APK. It never waited for the process to remain alive, checked the foreground activity, or failed on an app-scoped fatal exception. It therefore reported successful launches while the apps were crashing.

Archived `rc1` logcat evidence for Andacious, Gnuplot, and IDLE records the same fatal exception in `tech.ula.library.MainActivity`:

```text
Exception inflating ...:navigation/nav_graph line 6
Start destination 0 cannot use the same id as the graph
```

The shared library intentionally omits an XML start destination and tries to set it after `NavInflater.inflate()`. Navigation 2.5 validates the graph during inflation, so execution never reaches the runtime assignment. FoxBox worked because `rc1` built it with the older Navigation/Gradle profile.

The modern APK package dumps expose a second independent defect. They request only `READ_EXTERNAL_STORAGE`, while `PermissionHandler` requires both legacy read and write storage permissions before starting a session or importing/exporting a filesystem. Android 11 and later cannot grant that legacy pair to a target-35 application. The app would remain blocked even after the navigation crash was repaired.

## Selected approach

Use a focused shared-runtime repair rather than a full framework rewrite.

1. Refresh every launcher from its current upstream head.
2. Continue using the newest publicly reproducible shared library snapshot and apply exact, audited compatibility operations to it.
3. Repair navigation inflation and permission handling at the shared-library boundary so every launcher receives the same behavior.
4. Update the small native support payload bundled inside each APK to the latest verified upstream release.
5. Strengthen CI so a crash, launcher loop, missing permission contract, or dead process cannot pass as a successful launch.

A full Kotlin synthetic-to-ViewBinding migration, target-SDK-36 migration, and broad AndroidX upgrade are deferred. Combining those changes with the urgent runtime recovery would multiply the number of possible failure sources without being required to make the ten launchers usable on Android 16.

## Source and dependency policy

### Launcher sources

The lock file will point to each repository's current default-branch commit at implementation time. At design approval, nine launcher locks already matched their upstream heads. FoxBox advances from `72874faf7a7666dfbd782b22b1900b1ed26c8707` to `7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde`.

The FoxBox refresh moves it onto the same modern launcher baseline as the other nine apps: AGP 8.7.2, Gradle 8.9, Java 17, compile/target SDK 35, Navigation 2.5.0, and legacy JNI packaging. FoxBox will consume the modern shared compatibility profile after the refresh.

### Shared library

The current launcher submodules refer to `CypherpunkArmory/UserLAndLibrary` objects `513c819a...` or `499d7aa4...`. That repository is no longer publicly fetchable, and the objects are not available from the accessible fork. Those inaccessible pointers cannot be a reproducible build input.

The build will retain accessible commit `8751d21debb0f336b2437106db46bc708e81b7d3` from `Lily-Rader/UserLAndLibrary`, plus exact compatibility operations protected by anchor-count tests. The build must never silently fall back to an unavailable or floating submodule.

### Bundled native support assets

The shared library currently downloads support binaries from release `v1.3.4`. r2 will use the latest upstream release, `CypherpunkArmory/UserLAnd-Assets-Support` `v1.5.1`, published 2026-06-01. All four ABI archives will be checksum-locked:

| ABI archive | SHA-256 |
| --- | --- |
| `arm64-v8a-assets.zip` | `ec9bb2e652afb0ceab2cc6830809214ee4d786d31ef8463d0ec213aca67ff9ce` |
| `armeabi-v7a-assets.zip` | `af0a2667dbf90076fbc4bdde40538db84950bc596aabe24261a766ae57ccfe41` |
| `x86-assets.zip` | `9cb71e2e79fa0d1eb453cf669c8232e0000878a190f5c01f3f17cd01c06ca4d0` |
| `x86_64-assets.zip` | `897e0902202c6c07cb4efd9b0f00f5c33d5d2925092c62b3c14951ba7a371252` |

The dependency restorer will download, verify, cache, and stage these archives before Gradle runs. Gradle will consume the staged files and must not perform an unverified network download.

Desktop applications and Debian root filesystems remain first-run downloads. Embedding them would add hundreds of megabytes per APK, duplicate mutable upstream payloads ten times, and make every application update require a new Android release. r2 updates the small support runtime that belongs inside the APK while retaining externally updateable desktop payloads.

## Navigation repair

The shared navigation XML will receive a valid default start destination of `app_list_fragment`. `MainActivity.setNavStartDestination()` will continue selecting `session_list_fragment` or `app_list_fragment` from user preferences after inflation and before assigning the graph to the controller.

The compatibility test will apply the modern profile to a real fixture and assert both conditions:

- XML contains a nonzero start destination before inflation.
- Runtime code still overrides the destination using the stored preference.

No launcher-specific navigation fork will be created.

## Android permission model

The final merged manifest will use an explicit, auditable permission set. A manifest contract test and `aapt dump permissions` check will verify the produced APK rather than inferring permissions from source manifests.

### Normal permissions for all ten apps

- `INTERNET`
- `ACCESS_NETWORK_STATE`
- `ACCESS_WIFI_STATE`
- `CHANGE_WIFI_STATE`
- `WAKE_LOCK`
- `VIBRATE`
- `FOREGROUND_SERVICE`
- `FOREGROUND_SERVICE_SPECIAL_USE`

These permissions are granted at installation and do not produce runtime prompts.

`ServerService` will declare `android:foregroundServiceType="specialUse"` and an
explicit subtype describing its user-started Linux/SSH/VNC session runtime.
Android 14 and later require target-34+ applications to declare a foreground
service type and its matching permission; omitting them can crash the session
service even when the launcher activity itself is healthy.

### Conditional permissions

- Android 13+: `POST_NOTIFICATIONS`, requested immediately before functionality that starts the persistent session service.
- Android 11+: `MANAGE_EXTERNAL_STORAGE`, requested through the app-specific All Files Access settings screen only when starting a Linux session or another operation that binds shared public directories.
- Android 6-10: `READ_EXTERNAL_STORAGE` and `WRITE_EXTERNAL_STORAGE`, requested through the legacy runtime dialog.
- Andacious only: `RECORD_AUDIO`, because its launcher configuration sets `USES_MICROPHONE=true`.
- Camera is not requested by any r2 launcher because all ten set `USES_CAMERA=false`.

`PermissionHandler` will derive required access from the Android API level and launcher feature flags. It will not index fixed positions in `grantResults`. Denial returns the user to a clear explanation without a request loop. Returning from the All Files Access settings screen rechecks `Environment.isExternalStorageManager()` and resumes the pending action only when access is present.

The Storage Access Framework remains in use for importing and exporting backup files. All Files Access is needed for the live public-directory bindings exposed inside Linux sessions, not as a substitute for the document picker.

## Versioning and signing

- All APKs use `versionName=2026.08.29-r2`.
- Each APK uses the same monotonic r2 `versionCode`, greater than the code in `rc1` and within Android's signed 32-bit limit.
- Package IDs remain unchanged.
- The existing GitHub signing secrets and certificate fingerprint remain unchanged, allowing in-place updates from `rc1`.
- The release manifest records package ID, version name, version code, source commit, shared dependency commit, support asset release, APK SHA-256, and signing certificate SHA-256.

## Runtime verification

The emulator workflow will test the exact signed APK that is eligible for release.

For each of the ten packages, CI will:

1. Install the signed `rc1` APK when available and then install r2 with `adb install -r`, proving same-key upgrade and data retention.
2. Force-stop r2, clear logcat, and cold-launch its resolved launcher activity.
3. Wait conditionally for `tech.ula.library.MainActivity` to become the foreground activity.
4. Require the package PID to remain alive for at least 20 seconds after the shared activity is visible.
5. Fail on app-scoped `FATAL EXCEPTION`, `AndroidRuntime`, crash-buffer entries, ANRs, force-finish records, or unexpected process death.
6. Dump and summarize the UI hierarchy and require a non-system app window with visible content.
7. Capture a screenshot, full logcat, crash buffer, activity/task dump, package dump, and merged permission report.
8. Assert the installed version name ends in `r2`, the numeric version code increased, and the signing certificate matches the project key.
9. Exercise permission contracts on an Android 35 emulator: notification request for all apps, microphone request only for Andacious, and All Files Access handoff/recheck for a session-start path.

The test will not install the upgrade immediately after launch. Any crash that occurs during the stability window fails the matrix job and blocks release publication.

## Release gate

`v2026.08.29-r2` is published only when all of the following are green on the same commit:

- repository and lock-file contracts;
- checksummed source/dependency/support-asset restoration;
- ten signed release builds;
- package, version, and certificate inspection;
- ten rc1-to-r2 upgrade checks;
- ten sustained cold-launch checks;
- permission contract and flow checks;
- aggregate confirmation of exactly ten APK artifacts;
- release manifest and `SHA256SUMS` generation.

The release workflow will be idempotent: rerunning the same verified commit may replace assets on the same tag, but a tag that points to another commit is an error.

## Error handling

- A source head that changes after being inspected is not followed automatically; the resolved SHA is written to the lock.
- Missing or checksum-mismatched support assets stop before Gradle.
- An unavailable submodule pointer produces a clear reproducibility error instead of a fallback clone.
- A permission denial leaves the pending operation stopped and explains how to retry.
- A failed runtime check always uploads evidence, even when the build or emulator job fails.
- Release publication cannot run when any app matrix entry fails or omits evidence.

## Non-goals for r2

- Embedding full Debian root filesystems or desktop application packages in every APK.
- Migrating all synthetic Kotlin view access to ViewBinding.
- Moving compile/target SDK from the latest launcher baseline of 35 to 36.
- Updating every AndroidX library solely because a newer version exists.
- Changing package IDs, signing keys, app branding, or Obtainium repository layout.

Those upgrades can follow r2 as isolated, testable releases after the ten launchers are stable on the target device.

## Acceptance criteria

r2 is complete only when Zach can install or upgrade each of the ten signed APKs on the S23 Ultra, open it without an immediate crash, reach a usable UserLAnd first screen, receive only the permission prompts required by that launcher and Android version, and see `2026.08.29-r2` in package metadata. CI evidence must independently demonstrate the same launch and upgrade behavior before the release is offered.
