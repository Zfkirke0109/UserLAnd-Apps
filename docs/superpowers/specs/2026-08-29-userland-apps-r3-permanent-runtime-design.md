# UserLAnd Apps r3 Permanent Runtime Repair Design

**Date:** 2026-08-29

**Status:** Approved by the user with “Please continue” after presentation of the r3 design

## Goal

Release ten `2026.08.29-r3` APKs that complete a clean first-run download,
extract a usable Linux filesystem, start the selected application, recover
from interrupted setup, repair invalid r2 state, and visibly credit the
original UserLAnd Apps creators with a direct link to each official paid
Google Play listing.

## Evidence and Root Causes

The supplied Samsung Galaxy S23 Ultra Android 16 logcats and recording expose
three shared failures plus one recovery defect.

1. **Andacious host-tool failure.** Its two payloads complete, but every
   host-side BusyBox call fails because `busybox` requires
   `libbusybox.so.1.37.0` and the non-proot execution environment omits
   `LD_LIBRARY_PATH`. The activity closes while the session notification
   remains because the local server can never become ready.
2. **BirdBox false extraction success.** The v1.5.1 support script invokes
   `addNonRootUser.sh`, deletes `rootfs.tar.gz`, and writes the success marker,
   but it no longer extracts the root filesystem. The retained r2 runtime
   still delegates extraction to that script, so `/bin/bash` is absent and the
   script reports `addNonRootUser.sh: not found` while marking success.
3. **OEM DownloadManager starvation.** deVStudio, GIMP, and IDLE enqueue both
   requests into Samsung DownloadProvider, but the provider never transitions
   them to running. The application has no watchdog, timeout, retry, or
   transport fallback and therefore remains at `0 out of 2 complete`.
4. **Download-state re-entry failure.** GIMP shows that reopening an app while
   downloads are cached can submit `SessionSelected` into
   `DownloadingAssets`, producing `IncorrectSessionTransition` rather than
   reattaching to the active work.

FoxBox is a working control only because its Debian filesystem was already
extracted before r2. Gnuplot, R, LibreDocs, and Inky were not exercised in the
supplied recording; their clean-install behavior must be proven rather than
inferred. All ten share the affected library and release gate.

The r2 build verifier checked only `lib_arch.so`, `lib_assets.txt.so`,
`lib_busybox.so`, and `lib_proot.so`. It neither closed ELF dependencies nor
executed BusyBox, inspected the extraction contract, downloaded application
payloads, validated a root filesystem, or waited for a real session to become
ready. The previous 20-second activity check could therefore pass a broken
first-run path.

## Release Contract

- Release tag: `v2026.08.29-r3`
- Version name: `2026.08.29-r3`
- Version code: `2003329001`
- Upgrade source: public `v2026.08.29-r2`, version code `2003329000`
- APK signing identity: unchanged from r2 so installed r2 APKs update in place
- Support payload: `CypherpunkArmory/UserLAnd-Assets-Support` v1.5.1, retained
  with an explicit compatibility layer
- Android coverage: API 35 and API 36
- CPU payload coverage: all upstream-supported APK ABIs. Nine apps retain all
  four ABIs; deVStudio is limited to arm, arm64, and x86_64 because none of its
  published asset releases contains x86 payloads. Full session verification
  must cover the CI emulator ABI and build-time ELF closure must cover every
  packaged ABI.

## Architecture

### 1. Immutable Application Payload Catalog

`payloads.lock.json` is the source of truth for every launcher and ABI. Each
entry records the package ID, CypherpunkArmory asset repository, exact release
tag, release asset ID, immutable URL, byte length, SHA-256, and bundled
`assets.txt` entries for both `assets.tar.gz` and `rootfs.tar.gz`.

The catalog is generated from GitHub release metadata and downloaded bytes by
a deterministic repository tool. A matrix workflow computes hashes once, and
the aggregate verifier rejects missing apps, ABIs, files, sizes, digests,
duplicate package IDs, mutable `latest` selectors, and mismatched release
assets. The matrix contains 39 real combinations: four ABIs for nine apps and
three for deVStudio, whose APK excludes unsupported x86. Runtime setup reads
the catalog bundled into the APK and does not resolve GitHub `latest`.

Custom-filesystem mode remains supported, but its downloads are labelled
unlocked and must pass archive safety and completeness validation before use.

### 2. App-Owned Foreground Downloader

Android `DownloadManager` is removed from the UserLAnd setup path.
`AssetDownloadService` owns downloads in a `dataSync` foreground service and
uses the already-present OkHttp dependency. It starts only from a user-initiated
setup action and calls `startForeground()` immediately.

Each file is represented by a persisted journal record with a stable ID,
exact URL, destination, expected byte length, expected SHA-256, partial byte
count, attempt number, state, and the selected session/filesystem IDs. The
transport writes to `<name>.part`, resumes with an HTTP Range request, handles a
server that ignores Range by restarting safely, fsyncs before atomic publish,
and verifies length and SHA-256 before declaring success.

Network failures use five bounded attempts with exponential backoff. A lack of
read progress reaches an explicit timeout. Cancellation, checksum mismatch,
HTTP failure, and storage failure become durable terminal states with a clear
Retry action. Activity recreation and process restart reattach to the journal;
pending work is restarted rather than converted into an illegal transition.

The notification reports the current file and byte progress. It is removed on
success or terminal failure. The existing session notification remains
separate.

### 3. v1.5.1 BusyBox Compatibility

Host-side housekeeping and extraction use `busybox_static`. Dynamic BusyBox
remains available for support scripts, and every execution environment carries
the support directory in `LD_LIBRARY_PATH`.

Build verification parses every packaged ELF `DT_NEEDED` entry and requires a
matching staged library or an Android system allowlist entry. It also requires
`busybox_static`, `libbusybox.so.1.37.0`, the support scripts used by the
runtime, valid ABI markers, executable classifications, and a marker whose
file list exactly matches the staged directory.

### 4. Safe Root-Filesystem Extraction and r2 Repair

The application runtime—not the changed v1.5.1 helper script—owns rootfs
extraction. Before extraction it lists the gzip tar with static BusyBox and
rejects absolute paths, `..` traversal, empty names, and archive errors. It
then extracts into the app-private filesystem while preserving the downloaded
application support directory.

Only after extraction succeeds does the runtime enter proot to create the
non-root user. It then verifies at least `/bin/sh`, `/etc/passwd`, the selected
user home, and required application support files. The rootfs archive is
removed and `.success_filesystem_extraction` is written only after all checks
pass. Failure removes a stale success marker, writes a failure marker with a
safe reason, retains enough state for Retry, and stops session startup.

An r2 installation with a success marker but missing filesystem anchors is
treated as damaged. r3 invalidates only the false marker and re-extracts over
the private filesystem, preserving unrelated user-home content. A valid
existing FoxBox filesystem is not redownloaded or erased.

### 5. State Recovery and User-Facing Errors

The selected session and filesystem IDs travel with the persisted download
batch. On recreation, the state machine reloads those rows from Room before
emitting progress or completion. `SessionSelected` while the same batch is
active reattaches; a different selection requires an explicit cancel/replace
choice.

The progress view shows file count plus bytes. Terminal states describe the
failed stage and offer Retry and Repair instead of the generic GitHub error.
The state machine never advances from download, copy, extraction, or server
startup without its observable postcondition.

### 6. Creator Credit and Official Purchase Link

After the first successful session, r3 shows one dismissible creator-support
card. The same card remains available from a new **About & Support** menu item.
It never appears before or during setup and never blocks a repair.

The card contains:

- the installed app's existing `@mipmap/ic_main_launcher` artwork;
- Google's official English “Get it on Google Play” badge, stored locally with
  its source URL and SHA-256 provenance;
- credit to UserLAnd Technologies and the CypherpunkArmory contributors; and
- the text: “If you really like this app, show the creators of UserLAnd Apps
  some love and support by purchasing the official app on Google Play.”

The badge opens `market://details?id=<installed package>` and falls back to
`https://play.google.com/store/apps/details?id=<installed package>`. The ten
installed package IDs already match their official listings, including
`tech.ula.inkscape`, whose store title is currently Inky.

### 7. Verification and Release Gate

Repository tests must exercise real behavior rather than grep-only source
contracts wherever executable boundaries exist.

- Profile tests: safe overlay creation, exact intermediate hashes, ten-profile
  idempotence, and no path escape.
- Downloader tests with MockWebServer: fresh transfer, Range resume, server
  ignoring Range, timeout, HTTP error, retry ceiling, checksum mismatch,
  atomic publish, journal recreation, and cancellation.
- Runtime tests: static BusyBox selection, dynamic-library environment,
  malicious tar rejection, extraction failure, false-marker migration,
  anchor verification, and user-creation failure.
- Catalog tests: all 39 supported package/ABI combinations × two tar payloads
  with exact release, byte length, SHA-256, and bundled asset list.
- Credit tests: official package mapping, market URI, HTTPS fallback, one-time
  display state, permanent menu access, icon resource, and badge provenance.
- Emulator tests for every APK: r2 upgrade, clean-data first launch, both real
  payload downloads, interruption/resume, digest verification, extraction,
  filesystem anchors, session service readiness, visible application UI,
  relaunch, notification cleanup, and app-scoped crash/ANR scan on API 35 and
  API 36.

No r3 tag or release is created until all ten signed APKs and all required
device evidence bundles pass. The release contains the exact emulator-tested
APKs, `SHA256SUMS`, the release manifest, payload-lock provenance, and a concise
per-app verification table.

## Out of Scope

- Bundling all Linux root filesystems into each APK; this would add hundreds of
  megabytes per ABI and make updates unnecessarily large.
- Replacing the unavailable upstream UserLAndLibrary wholesale.
- Granting camera, microphone, or storage permissions beyond each launcher's
  actual feature requirements.
- Claiming Samsung-device verification from a generic emulator. The supplied
  Samsung failure mode is eliminated by removing DownloadManager dependency,
  while final S23 Ultra confirmation remains a post-release device check.
