# UserLAnd Apps

[![Build and verify UserLAnd apps](https://github.com/Zfkirke0109/UserLAnd-Apps/actions/workflows/ci.yml/badge.svg)](https://github.com/Zfkirke0109/UserLAnd-Apps/actions/workflows/ci.yml)

This repository reproducibly builds ten independently installable Android launchers derived from UserLAnd. Launcher sources, the shared UserLAnd library, native dependencies, and support assets are pinned to exact public commits or SHA-256 checksums.

## r2 status

**Verified r2 release.** All ten apps passed signed build verification and one clean Android 35 emulator matrix at version `2026.08.29-r2`. Each app upgraded from its published rc1 APK, cold-launched, stayed alive for the 20-second stability window, exposed usable UI, completed the notification and All Files Access handoffs, resumed after Settings, and produced no app-scoped fatal exception, ANR, or force-finish event.

- [Download v2026.08.29-r2](https://github.com/Zfkirke0109/UserLAnd-Apps/releases/tag/v2026.08.29-r2)
- [Ten-app runtime and upgrade evidence](https://github.com/Zfkirke0109/UserLAnd-Apps/actions/runs/33255923668)
- [Independent signed-build verification](https://github.com/Zfkirke0109/UserLAnd-Apps/actions/runs/33255923710)

The rc1 APKs are retained only as upgrade-test inputs and are not recommended for normal use. Their emulator test could pass before an immediate crash occurred.

| App | Android package | APK | Obtainium APK filter | r2 status |
| --- | --- | --- | --- | --- |
| FoxBox | `tech.ula.foxbox_pro` | `FoxBox.apk` | `^FoxBox\.apk$` | Verified |
| Andacious | `tech.ula.andacious` | `Andacious.apk` | `^Andacious\.apk$` | Verified |
| Gnuplot | `tech.ula.gnuplot` | `Gnuplot.apk` | `^Gnuplot\.apk$` | Verified |
| R | `tech.ula.r` | `R.apk` | `^R\.apk$` | Verified |
| LibreDocs | `tech.ula.libredocs` | `LibreDocs.apk` | `^LibreDocs\.apk$` | Verified |
| deVStudio | `tech.ula.devstudio` | `deVStudio.apk` | `^deVStudio\.apk$` | Verified |
| Inkscape | `tech.ula.inkscape` | `Inkscape.apk` | `^Inkscape\.apk$` | Verified |
| BirdBox | `tech.ula.birdbox` | `BirdBox.apk` | `^BirdBox\.apk$` | Verified |
| GIMP | `tech.ula.gimp` | `GIMP.apk` | `^GIMP\.apk$` | Verified |
| IDLE | `tech.ula.idle` | `IDLE.apk` | `^IDLE\.apk$` | Verified |

## What changed in r2

- The shared Navigation graph has a valid initial destination before Android inflates it, removing the startup crash shared by the nine modern launchers.
- FoxBox now uses the same Android Gradle 8, target SDK 35, and JDK 17 compatibility baseline as the other launchers.
- All APKs bundle the checksummed native files from **UserLAnd-Assets-Support v1.5.1** for `arm64-v8a`, `armeabi-v7a`, `x86`, and `x86_64`.
- The permission flow follows current Android behavior instead of asking for broad legacy permissions at every launch.
- Android 13+ download broadcasts use the required receiver-export flag without relying on an incompatible support-library overload.
- Session startup falls back to a direct Room lookup when its LiveData filesystem cache is briefly stale, removing the post-Settings first-run crash.
- Runtime QA upgrades the real rc1 APK, cold-launches r2, checks one stable process for at least 20 seconds, scans for crashes/ANRs, and captures UI and permission evidence.

The support archives are the practical small runtime update that can be bundled safely in each APK. Full Linux distributions, desktop packages, and application payloads remain **first-run downloads**: embedding all of them would make each launcher extremely large and would duplicate fast-changing upstream packages across ten APKs.

## Permissions

The APKs request the minimum access needed by the shared runtime:

| Access | Scope | Why it is used |
| --- | --- | --- |
| `INTERNET`, network state, Wi-Fi state | All apps | Download distributions and connect local/remote sessions. |
| `POST_NOTIFICATIONS` | Android 13+ | Display the foreground session notification when a Linux session starts. |
| `MANAGE_EXTERNAL_STORAGE` | Android 11+ session setup | Allow an explicitly approved session to bind public shared-storage directories. Android opens the system settings screen for this special access. |
| Legacy `READ_EXTERNAL_STORAGE` / `WRITE_EXTERNAL_STORAGE` | Android 10 and older only | Preserve shared-folder behavior on older devices; both declarations are capped with `maxSdkVersion=29`. |
| `RECORD_AUDIO` | Andacious only | Audio capture for that launcher's intended workload. |

No launcher requests camera access. File import/export uses Android's document picker and does not require blanket storage permission. Denial does not cause a repeated permission loop; the app can recheck special access after returning from Settings.

## Install and update

The [v2026.08.29-r2 release](https://github.com/Zfkirke0109/UserLAnd-Apps/releases/tag/v2026.08.29-r2) contains the ten emulator-verified signed APKs, `SHA256SUMS`, and `release-manifest.json`. The manifest records every source SHA, the shared library revision, support-asset checksums, exact package/version metadata, and the signing certificate.

For update notifications, add this repository URL to [Obtainium](https://github.com/ImranR98/Obtainium) once per app and use its exact APK filter from the table:

```text
https://github.com/Zfkirke0109/UserLAnd-Apps
```

These builds use the project signing key rather than the original publisher key. An original publisher-signed installation must be uninstalled once before installing this repository's APK. Back up needed app data first. The signed r2 APKs are then tested as in-place upgrades from this repository's rc1 release.

Expected signing certificate SHA-256:

```text
82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC
```

## Reproducible inputs

- `release.lock.json` fixes the release tag, visible version name, numeric Android version code, and rc1 upgrade source.
- `sources.lock.json` pins every launcher repository and commit.
- `dependencies.lock.json` pins UserLAndLibrary, Termux, remote-desktop clients, FreeRDP, the historical native archive, and four UserLAnd support archives.
- `apps/<id>/SOURCE.json` records imported launcher provenance.
- `profiles/<id>.json` applies exact-anchor compatibility fixes without rewriting the vendored source snapshots.
- `tools/release_manifest.py` rejects any APK whose package, r2 version, SDK target, or certificate differs from the locks.

The dependency update is deliberately bounded: r2 refreshes the launcher baseline and adds the latest available UserLAnd-Assets-Support release while retaining exact revisions required by the historical native stack. Updating every Gradle, Kotlin, terminal, remote-desktop, and native dependency at once would be a separate platform migration and would make the launch regression harder to isolate.

## Local validation and build

Run repository contracts:

```bash
python3 -m unittest discover -s tests -v
python3 tools/validate_contract.py
```

Restore the shared source and checksummed native assets:

```bash
scripts/prepare_dependencies.sh dependencies.lock.json build/shared .cache/dependencies
```

A signed build requires JDK 17, Android SDK platforms 31 and 35, Build Tools 30.0.3 and 35.0.0, and the four signing environment values used by the workflows. `build_app.sh` reads the r2 version directly from `release.lock.json`:

```bash
scripts/build_app.sh foxbox
```

Do not commit keystores, Base64 key material, aliases, or passwords. GitHub Actions receives them only through repository secrets.

## Locked launcher sources

| App | Source commit |
| --- | --- |
| FoxBox | `Zfkirke0109/FoxBox@7f08dcf54fcae40bb96fd20e1c057c8ac89c2fde` |
| Andacious | `Zfkirke0109/Andacious@ecf655a09672b6f32a77e21db69d16b0973f59c4` |
| Gnuplot | `Zfkirke0109/Gnuplot@f08f9de7dcb6807f26fb7a3f7d30aa3e483458c1` |
| R | `Zfkirke0109/R@7c6c4c92cca9fba35cd9d04af84a5b94e1f95153` |
| LibreDocs | `Zfkirke0109/LibreDocs@2758a023bd99adc36419090a3d588cd42c1862db` |
| deVStudio | `Zfkirke0109/deVStudio@7a0e5a34a1facdff58aa939433885267baaf4b96` |
| Inkscape | `Zfkirke0109/Inkscape@9ee89399be6089a65adac118079e2d4615d2bff6` |
| BirdBox | `Zfkirke0109/BirdBox@1ab3f48a4b1f691abd072a5f45471504ae1d6374` |
| GIMP | `Zfkirke0109/GIMP@a74281ee21f1eb5e460a6204cb954dbd059675df` |
| IDLE | `Zfkirke0109/IDLE@f2728037ecf1767b4e550cbc53c68d6964b9cd42` |

The original upstream licenses remain in each vendored launcher directory.
