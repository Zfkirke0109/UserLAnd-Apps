# UserLAnd Apps Monorepo Design

**Status:** Approved in chat on 2026-08-29  
**Repository:** `Zfkirke0109/UserLAnd-Apps`

## Goal

Create one public, reproducible repository that builds independently installable Android APKs for FoxBox, Andacious, Gnuplot, R, LibreDocs, deVStudio, Inkscape, BirdBox, GIMP, and IDLE. Reuse the proven FoxBox compatibility repairs where applicable, sign every release with one permanent project-owned Android key, and publish GitHub Releases suitable for Obtainium-based updates.

## Application inventory

| App | Package ID | Initial source |
| --- | --- | --- |
| FoxBox | `tech.ula.foxbox_pro` | `Zfkirke0109/FoxBox@72874faf7a7666dfbd782b22b1900b1ed26c8707` |
| Andacious | `tech.ula.andacious` | `Zfkirke0109/Andacious@ecf655a09672b6f32a77e21db69d16b0973f59c4` |
| Gnuplot | `tech.ula.gnuplot` | `Zfkirke0109/Gnuplot@f08f9de7dcb6807f26fb7a3f7d30aa3e483458c1` |
| R | `tech.ula.r` | `Zfkirke0109/R@7c6c4c92cca9fba35cd9d04af84a5b94e1f95153` |
| LibreDocs | `tech.ula.libredocs` | `Zfkirke0109/LibreDocs@2758a023bd99adc36419090a3d588cd42c1862db` |
| deVStudio | `tech.ula.devstudio` | `Zfkirke0109/deVStudio@7a0e5a34a1facdff58aa939433885267baaf4b96` |
| Inkscape | `tech.ula.inkscape` | `Zfkirke0109/Inkscape@9ee89399be6089a65adac118079e2d4615d2bff6` |
| BirdBox | `tech.ula.birdbox` | `Zfkirke0109/BirdBox@1ab3f48a4b1f691abd072a5f45471504ae1d6374` |
| GIMP | `tech.ula.gimp` | `Zfkirke0109/GIMP@a74281ee21f1eb5e460a6204cb954dbd059675df` |
| IDLE | `tech.ula.idle` | `Zfkirke0109/IDLE@f2728037ecf1767b4e550cbc53c68d6964b9cd42` |

`UserLAnd-Assets-Support` is shared input and provenance, not an APK-producing application.

## Source architecture

The repository is a source monorepo. Each launcher is imported beneath `apps/<app-id>/` without its broken `UserLAndLibrary` gitlink. A machine-readable `sources.lock.json` records every source repository, commit, package ID, asset source, and compatibility profile.

The vanished upstream `CypherpunkArmory/UserLAndLibrary` commits `513c819...` and `499d7aa...` will not be referenced. The build uses the publicly preserved `Lily-Rader/UserLAndLibrary@8751d21debb0f336b2437106db46bc708e81b7d3`, plus the pinned remote-desktop, Termux, FreeRDP, and native dependency revisions proven by FoxBox.

For each launcher, the implementation first applies focused compatibility changes to its locked current source. If the launcher API cannot be reconciled with the preserved library without changing app behavior, the importer deterministically selects the newest ancestor that compiles against the preserved library, locks that commit, and records the downgrade reason. No build silently changes source revisions.

## Shared build logic

A single compatibility layer prepares dependencies for every app:

1. Restore pinned UserLAndLibrary, remote-desktop, Termux, FreeRDP, and native archives.
2. Download native archives with retries, timeouts, SHA-256 validation, archive validation, and caching.
3. Normalize the historical FreeRDP directory layout without deleting native libraries.
4. Make FreeRDP version discovery safe outside its original Git history.
5. Replace retired JCenter/Bintray dependencies and publishing plugins only when detected.
6. Provide the legacy Gradle/Android properties required by the selected source.
7. Define and validate `android:exported` for all components with intent filters.
8. Apply app-specific patches from isolated profile files; a patch for one app must not affect another.

The compatibility scripts are fail-closed: missing expected anchors, changed checksums, incomplete dependency trees, unexpected package IDs, or unsigned outputs fail the job.

## Continuous integration

One GitHub Actions matrix builds all ten apps independently. A failure in one matrix entry does not hide results for the other apps, while the aggregate job fails until every required app succeeds.

Each job:

- imports or uses the locked launcher source;
- prepares the shared dependency tree;
- selects the required JDK and Android SDK/build-tools versions;
- runs Gradle configuration checks and `:app:assembleRelease`;
- verifies the APK package ID, version code, certificate, signature schemes, and manifest parsing;
- uploads logs and the APK as workflow artifacts.

Dependency archives and Gradle state are cached using keys that include every source revision, checksum, and compatibility-script hash.

## Release signing

Release builds use exactly these GitHub Actions secrets:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

The configured key is the new project-owned key generated for Zach, not CypherpunkArmory's unavailable publisher key. Its expected certificate SHA-256 fingerprint is:

`82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC`

CI must compare every release APK against that fingerprint and fail on any mismatch. Users with publisher-signed versions must uninstall them once before installing these builds. After the first project-signed installation, later GitHub releases update normally.

The keystore and secret values are never committed, echoed, uploaded as artifacts, or included in logs.

## Releases and updates

A successful release workflow creates one GitHub Release containing:

- ten clearly named signed APKs;
- `SHA256SUMS`;
- `release-manifest.json` with package IDs, version codes, source commits, certificate fingerprint, minimum SDK, target SDK, and asset URLs;
- release notes identifying any source revision fallback or compatibility limitation.

Stable filenames and monotonically increasing version codes make the release feed usable by Obtainium. A direct in-app self-updater is outside the initial scope because it would add privileged download/install code to ten legacy applications.

## Verification

An app is complete only when:

1. its release task succeeds from a clean GitHub-hosted runner;
2. `apksigner verify --verbose --print-certs` passes and reports the locked certificate;
3. package ID and version code match the lock manifest;
4. Android manifest parsing succeeds and no intent-filter component lacks `android:exported`;
5. installation and main-activity launch succeed on an Android emulator at the supported API level;
6. a second build with a higher test version code installs as an update over the first build without a signature conflict;
7. the release contains the expected APK, checksum, and manifest entry.

Desktop payload startup requires device-level smoke testing because these apps depend on Linux assets, remote-display components, and runtime downloads. Any app that builds and launches but cannot start its advertised desktop payload remains incomplete and is documented rather than presented as working.

## Repository policy

- Source provenance and upstream licenses are retained.
- No private keys, passwords, tokens, or generated keystores enter Git history.
- No floating branches or unverified remote archives are used in release builds.
- Compatibility fixes are centralized when shared and isolated when app-specific.
- Pull requests must pass source-lock validation and the affected application build before merge.
