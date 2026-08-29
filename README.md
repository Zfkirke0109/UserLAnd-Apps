# UserLAnd Apps

[![Build and verify UserLAnd apps](https://github.com/Zfkirke0109/UserLAnd-Apps/actions/workflows/ci.yml/badge.svg)](https://github.com/Zfkirke0109/UserLAnd-Apps/actions/workflows/ci.yml)

This repository reproducibly builds ten independently installable Android launchers derived from UserLAnd. Each launcher source and every shared native dependency is pinned to an exact public commit or SHA-256 checksum. `UserLAnd-Assets-Support` is a shared runtime input, not an eleventh APK.

## App status

No app is marked complete until its signed matrix build and install/launch/upgrade emulator test both pass.

| App | Android package | APK | Verification status |
| --- | --- | --- | --- |
| FoxBox | `tech.ula.foxbox_pro` | `FoxBox.apk` | Pending first monorepo CI and upgrade-smoke run |
| Andacious | `tech.ula.andacious` | `Andacious.apk` | Pending first monorepo CI and upgrade-smoke run |
| Gnuplot | `tech.ula.gnuplot` | `Gnuplot.apk` | Pending first monorepo CI and upgrade-smoke run |
| R | `tech.ula.r` | `R.apk` | Pending first monorepo CI and upgrade-smoke run |
| LibreDocs | `tech.ula.libredocs` | `LibreDocs.apk` | Pending first monorepo CI and upgrade-smoke run |
| deVStudio | `tech.ula.devstudio` | `deVStudio.apk` | Pending first monorepo CI and upgrade-smoke run |
| Inkscape | `tech.ula.inkscape` | `Inkscape.apk` | Pending first monorepo CI and upgrade-smoke run |
| BirdBox | `tech.ula.birdbox` | `BirdBox.apk` | Pending first monorepo CI and upgrade-smoke run |
| GIMP | `tech.ula.gimp` | `GIMP.apk` | Pending first monorepo CI and upgrade-smoke run |
| IDLE | `tech.ula.idle` | `IDLE.apk` | Pending first monorepo CI and upgrade-smoke run |

## Install and update

Signed APKs will be attached to the [latest GitHub Release](https://github.com/Zfkirke0109/UserLAnd-Apps/releases/latest). The release also contains `SHA256SUMS` and `release-manifest.json` for independent package, version, source, and certificate verification.

For update notifications and installation, add this repository URL to [Obtainium](https://github.com/ImranR98/Obtainium):

```text
https://github.com/Zfkirke0109/UserLAnd-Apps
```

Select the APK matching the installed app. GitHub Releases is the update feed; the APKs do not contain a custom in-app updater.

### One-time signing migration

These builds use a new project signing key, not the original publisher key. Android will reject an in-place update from an original publisher-signed installation. Uninstall that installation once, then install this repository's APK. Back up any app data you need first. Future releases from this repository can update in place when the package ID is unchanged.

Expected signing certificate SHA-256:

```text
82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC
```

## Reproducible source layout

- `sources.lock.json` pins each launcher repository and commit.
- `dependencies.lock.json` pins UserLAndLibrary, Termux, remote-desktop clients, FreeRDP, and the native archive checksum.
- `apps/<id>/SOURCE.json` records imported launcher provenance.
- `profiles/<id>.json` applies exact-anchor compatibility fixes without changing the vendored source snapshots.
- GitHub Actions rebuilds, signs, inspects, and uploads each APK independently.

The compatibility layer carries forward the fixes proven by the FoxBox build: verified dependency downloads, the historical FreeRDP layout, safe version discovery outside a Git checkout, retired JCenter/Bintray removal, the available SSH library version, required legacy Android properties and Build Tools, and Android 12 component exports.

## Local validation

Run the complete source and workflow contract suite:

```bash
python3 -m unittest discover -s tests -v
python3 tools/validate_contract.py
```

Restore the shared source/native tree:

```bash
scripts/prepare_dependencies.sh dependencies.lock.json build/shared .cache/dependencies
```

A local signed build additionally needs Android SDK platforms 31 and 35, Build Tools 30.0.3 and 35.0.0, JDK 11 for FoxBox or JDK 17 for the other launchers, and the four signing environment values documented in the workflows. Example after signing preparation:

```bash
scripts/build_app.sh foxbox 2000000001 local.1
```

Do not commit keystores, Base64 key material, aliases, or passwords. GitHub Actions receives them only through repository secrets.

## Runtime assets

An APK build proves Android packaging and signature compatibility, not that every upstream runtime asset remains available forever. The emulator workflow verifies install, launcher resolution, launch, and same-key upgrade. First-run distribution downloads and desktop application payloads still depend on the URLs encoded by each pinned launcher and should be treated as a separate runtime check.

## Locked launcher sources

| App | Source commit |
| --- | --- |
| FoxBox | `Zfkirke0109/FoxBox@72874faf7a7666dfbd782b22b1900b1ed26c8707` |
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
