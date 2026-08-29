# UserLAnd Apps Monorepo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build, verify, sign, and publish ten independently installable UserLAnd-derived Android APKs from one public reproducible repository.

**Architecture:** Vendor only launcher-owned source beneath apps/, reconstruct the shared historical UserLAnd dependency tree from cryptographically locked public sources, and build each launcher through one compatibility/profile interface. GitHub Actions runs a ten-entry matrix and publishes one signed release feed with machine-readable provenance.

**Tech Stack:** Android Gradle Plugin/Gradle from the locked launcher sources, Bash, Python 3 standard library, JDK 11 and 17, Android SDK command-line tools, GitHub Actions, keytool, apksigner, adb.

**Spec:** docs/superpowers/specs/2026-08-29-userland-apps-design.md

## Global Constraints

- APK set: FoxBox, Andacious, Gnuplot, R, LibreDocs, deVStudio, Inkscape, BirdBox, GIMP, and IDLE.
- UserLAnd-Assets-Support is shared input and provenance, not an APK-producing application.
- Shared library source: Lily-Rader/UserLAndLibrary@8751d21debb0f336b2437106db46bc708e81b7d3.
- Remote desktop source: CypherpunkArmory/remote-desktop-clients@408a5d3e2753f12f07430f816eaa3e40e9337462.
- Termux source: CypherpunkArmory/termux-app@6833f4a898ae8afa45172c87e9ce20afd8a8fb52.
- FreeRDP source: FreeRDP/FreeRDP@c0020308ebd33cefbd4548f03697f0c186a3631b.
- Native archive SHA-256: b8cbc1a46ca3237c7002d46737e01b3d9245c70fb78586114402a121a77b140c.
- Release certificate SHA-256: 82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC.
- Signing inputs exist only as ANDROID_KEYSTORE_BASE64, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS, and ANDROID_KEY_PASSWORD GitHub Actions secrets.
- Release version codes use 2000000000 + github.run_number and must remain at or below 2100000000.
- No floating source refs, unverified archives, secrets in Git history, or signing values in logs.
- GitHub Releases and Obtainium are the update channel; no direct in-app updater is added.
- Publisher-signed installations require one uninstall before the first project-signed installation.
- Each app remains incomplete until clean-runner build, signature, manifest, emulator install/launch, and signed upgrade tests pass.

## File structure

- sources.lock.json — launcher source commits, package IDs, versions, and compatibility profiles.
- dependencies.lock.json — shared repository commits, archive URL, and checksum.
- apps/<app-id>/ — imported launcher-owned source with the broken UserLAndLibrary gitlink removed.
- profiles/<app-id>.json — deterministic app-specific compatibility operations.
- tools/validate_contract.py — validates both lock files and profile coverage.
- tools/import_sources.py — safely imports locked launcher archives.
- tools/apply_compat.py — applies typed, anchor-checked compatibility operations.
- tools/release_manifest.py — inspects APKs and emits release-manifest.json plus SHA256SUMS.
- scripts/prepare_dependencies.sh — reconstructs and verifies the shared dependency tree.
- scripts/prepare_signing.sh — decodes and validates the release keystore without logging secrets.
- scripts/build_app.sh — creates an isolated workspace and runs one release build.
- build-logic/signing.gradle — common environment-backed release signing configuration.
- tests/ — standard-library unit and contract tests.
- .github/workflows/ci.yml — unsigned contract tests plus signed ten-app build matrix.
- .github/workflows/release.yml — tag-triggered signed build and GitHub Release publication.
- .github/workflows/upgrade-smoke.yml — emulator installation, launch, and signed upgrade validation.
- README.md — app status, release/install/update instructions, signing migration warning, and provenance.

---

### Task 1: Source and dependency contracts

**Files:**
- Create: sources.lock.json
- Create: dependencies.lock.json
- Create: tools/validate_contract.py
- Create: tests/test_validate_contract.py

**Interfaces:**
- Consumes: approved package IDs and source commits from the design specification.
- Produces: load_json(path: Path) -> dict and validate_contract(root: Path) -> list[str]; later tasks stop when the returned error list is non-empty.

- [ ] **Step 1: Write the failing contract tests**

~~~python
# tests/test_validate_contract.py
import json
import tempfile
import unittest
from pathlib import Path
from tools.validate_contract import validate_contract

class ContractTests(unittest.TestCase):
    def test_repository_contract_is_complete(self):
        self.assertEqual([], validate_contract(Path(".")))

    def test_duplicate_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = json.loads(Path("sources.lock.json").read_text())
            source["apps"][1]["package_id"] = source["apps"][0]["package_id"]
            (root / "sources.lock.json").write_text(json.dumps(source))
            (root / "dependencies.lock.json").write_text(
                Path("dependencies.lock.json").read_text()
            )
            errors = validate_contract(root)
            self.assertIn("duplicate package_id: tech.ula.foxbox_pro", errors)

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Run the tests and confirm the red state**

Run: python3 -m unittest tests.test_validate_contract -v  
Expected: ERROR because tools.validate_contract does not exist.

- [ ] **Step 3: Create the exact lock documents**

sources.lock.json must contain ten objects with keys id, display_name, package_id, repository, source_ref, profile, and output_name. Lock FoxBox to 72874faf7a7666dfbd782b22b1900b1ed26c8707 and the other nine refs from the spec inventory. Use output names FoxBox.apk, Andacious.apk, Gnuplot.apk, R.apk, LibreDocs.apk, deVStudio.apk, Inkscape.apk, BirdBox.apk, GIMP.apk, and IDLE.apk.

dependencies.lock.json must contain:

~~~json
{
  "userland_library": {
    "repository": "Lily-Rader/UserLAndLibrary",
    "ref": "8751d21debb0f336b2437106db46bc708e81b7d3"
  },
  "remote_desktop_clients": {
    "repository": "CypherpunkArmory/remote-desktop-clients",
    "ref": "408a5d3e2753f12f07430f816eaa3e40e9337462"
  },
  "termux_app": {
    "repository": "CypherpunkArmory/termux-app",
    "ref": "6833f4a898ae8afa45172c87e9ce20afd8a8fb52"
  },
  "freerdp": {
    "repository": "FreeRDP/FreeRDP",
    "ref": "c0020308ebd33cefbd4548f03697f0c186a3631b"
  },
  "native_archive": {
    "url": "https://github.com/iiordanov/remote-desktop-clients/releases/download/dependencies/remote-desktop-clients-libs-1.tar.gz",
    "sha256": "b8cbc1a46ca3237c7002d46737e01b3d9245c70fb78586114402a121a77b140c"
  }
}
~~~

- [ ] **Step 4: Implement strict validation**

~~~python
# tools/validate_contract.py
import json
import re
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
APP_KEYS = {"id", "display_name", "package_id", "repository",
            "source_ref", "profile", "output_name"}

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def validate_contract(root: Path) -> list[str]:
    errors = []
    sources = load_json(root / "sources.lock.json")
    dependencies = load_json(root / "dependencies.lock.json")
    apps = sources.get("apps", [])
    if len(apps) != 10:
        errors.append(f"expected 10 apps, found {len(apps)}")
    packages = set()
    ids = set()
    for app in apps:
        missing = APP_KEYS - set(app)
        if missing:
            errors.append(f"{app.get('id', '<unknown>')} missing: {sorted(missing)}")
        if app.get("id") in ids:
            errors.append(f"duplicate id: {app['id']}")
        ids.add(app.get("id"))
        if app.get("package_id") in packages:
            errors.append(f"duplicate package_id: {app['package_id']}")
        packages.add(app.get("package_id"))
        if not SHA.fullmatch(app.get("source_ref", "")):
            errors.append(f"{app.get('id')} has non-SHA source_ref")
    for name in ("userland_library", "remote_desktop_clients",
                 "termux_app", "freerdp"):
        if not SHA.fullmatch(dependencies.get(name, {}).get("ref", "")):
            errors.append(f"{name} has non-SHA ref")
    archive_hash = dependencies.get("native_archive", {}).get("sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", archive_hash):
        errors.append("native archive SHA-256 is invalid")
    return errors
~~~

Add a main block that prints each error to stderr and exits 1, otherwise prints Contract valid: 10 apps and exits 0.

- [ ] **Step 5: Run validation**

Run: python3 -m unittest tests.test_validate_contract -v && python3 tools/validate_contract.py  
Expected: 2 tests pass and Contract valid: 10 apps.

- [ ] **Step 6: Commit**

~~~bash
git add sources.lock.json dependencies.lock.json tools/validate_contract.py tests/test_validate_contract.py
git commit -m "build: lock UserLAnd app and dependency sources"
~~~

### Task 2: Safe source importer and vendored launcher snapshots

**Files:**
- Create: tools/import_sources.py
- Create: tests/test_import_sources.py
- Create: apps/foxbox/
- Create: apps/andacious/
- Create: apps/gnuplot/
- Create: apps/r/
- Create: apps/libredocs/
- Create: apps/devstudio/
- Create: apps/inkscape/
- Create: apps/birdbox/
- Create: apps/gimp/
- Create: apps/idle/

**Interfaces:**
- Consumes: validated sources.lock.json.
- Produces: import_app(app: dict, destination: Path) -> None; every apps/<id>/ tree contains app/, CustomLibrary/, Gradle wrapper files, settings.gradle, build.gradle, gradle.properties, LICENSE, and SOURCE.json but never .git or UserLAndLibrary.

- [ ] **Step 1: Write archive safety and exclusion tests**

~~~python
# tests/test_import_sources.py
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from tools.import_sources import extract_launcher

class ImportTests(unittest.TestCase):
    def test_excludes_gitlink_and_github_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                for name, body in (
                    ("repo/app/build.gradle", b"android {}"),
                    ("repo/UserLAndLibrary", b"gitlink"),
                    ("repo/.github/workflows/build.yml", b"workflow"),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    output.addfile(info, io.BytesIO(body))
            destination = Path(directory) / "app"
            extract_launcher(archive, destination)
            self.assertTrue((destination / "app/build.gradle").is_file())
            self.assertFalse((destination / "UserLAndLibrary").exists())
            self.assertFalse((destination / ".github").exists())

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("repo/../../escape")
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                extract_launcher(archive, Path(directory) / "app")

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Confirm tests fail**

Run: python3 -m unittest tests.test_import_sources -v  
Expected: ERROR because tools.import_sources does not exist.

- [ ] **Step 3: Implement the importer**

Use urllib.request to fetch https://api.github.com/repos/{repository}/tarball/{source_ref}. extract_launcher must strip the single archive root, reject absolute paths or any .. path component, and skip .git, .github, UserLAndLibrary, local.properties, build/, and .gradle/. After extraction, write SOURCE.json containing repository, source_ref, imported_at_utc, and exclusions. Refuse to overwrite a non-empty destination unless --replace is supplied.

- [ ] **Step 4: Run importer tests**

Run: python3 -m unittest tests.test_import_sources -v  
Expected: 2 tests pass.

- [ ] **Step 5: Import all locked sources**

Run: python3 tools/import_sources.py --lock sources.lock.json --destination apps  
Expected: Imported 10/10 launchers; python3 tools/validate_contract.py still exits 0; find apps -name UserLAndLibrary returns no results.

- [ ] **Step 6: Verify provenance and required files**

Run: python3 -c "import json,pathlib; roots=list(pathlib.Path('apps').glob('*/SOURCE.json')); assert len(roots)==10; [json.loads(p.read_text()) for p in roots]"  
Expected: exit 0.

- [ ] **Step 7: Commit**

~~~bash
git add tools/import_sources.py tests/test_import_sources.py apps
git commit -m "feat: vendor locked UserLAnd launcher sources"
~~~

### Task 3: Reproducible shared dependency restoration

**Files:**
- Create: scripts/prepare_dependencies.sh
- Create: tools/verify_dependency_tree.py
- Create: tests/test_verify_dependency_tree.py

**Interfaces:**
- Consumes: dependencies.lock.json and an empty output directory.
- Produces: prepare_dependencies.sh LOCK OUTPUT CACHE; OUTPUT/UserLAndLibrary is complete and verify_dependency_tree(root: Path) -> list[str] returns an empty list.

- [ ] **Step 1: Write the failing tree test**

~~~python
# tests/test_verify_dependency_tree.py
import tempfile
import unittest
from pathlib import Path
from tools.verify_dependency_tree import verify_dependency_tree

class DependencyTreeTests(unittest.TestCase):
    def test_missing_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = verify_dependency_tree(Path(directory))
            self.assertTrue(any("UserLAndLibrary/app/build.gradle" in e for e in errors))

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Confirm the red state**

Run: python3 -m unittest tests.test_verify_dependency_tree -v  
Expected: ERROR because tools.verify_dependency_tree does not exist.

- [ ] **Step 3: Implement the required-file verifier**

The required list must include UserLAndLibrary/app/build.gradle, both Termux library build.gradle files, bVNC/build.gradle, pubkeyGenerator/build.gradle, remoteClientLib/build.gradle, FreeRDP freeRDPCore/build.gradle, its AndroidManifest.xml, and the three armeabi-v7a FreeRDP native libraries checked by the FoxBox workflow. Return one missing or empty: <relative path> error per absent file.

- [ ] **Step 4: Implement dependency restoration**

prepare_dependencies.sh must:

- parse lock values with python3 rather than jq;
- clone each repository at its exact SHA with fetch-depth 1;
- cache the native archive under CACHE using its SHA-256 in the filename;
- download to a .part file with curl --fail --location --connect-timeout 20 --max-time 300 and five attempts with 1, 2, 4, and 8 second backoff;
- validate sha256sum, gzip -t, and tar -tzf before promotion;
- run download-prebuilt-dependencies.sh with TAR_OPTIONS=--no-same-owner;
- normalize extracted FreeRDP into remoteClientLib/jni/libs/deps/FreeRDP;
- overlay the locked FreeRDP source with rsync --exclude=.git without deleting prebuilt libraries;
- invoke tools/verify_dependency_tree.py and fail on any error.

- [ ] **Step 5: Run unit and live restoration checks**

Run: python3 -m unittest tests.test_verify_dependency_tree -v  
Expected: 1 test passes.

Run: scripts/prepare_dependencies.sh dependencies.lock.json build/shared .cache/dependencies  
Expected: Dependency tree verified; exit 0.

- [ ] **Step 6: Commit**

~~~bash
git add scripts/prepare_dependencies.sh tools/verify_dependency_tree.py tests/test_verify_dependency_tree.py
git commit -m "build: restore pinned UserLAnd native dependencies"
~~~

### Task 4: Anchor-checked compatibility profiles

**Files:**
- Create: profiles/foxbox.json
- Create: profiles/andacious.json
- Create: profiles/gnuplot.json
- Create: profiles/r.json
- Create: profiles/libredocs.json
- Create: profiles/devstudio.json
- Create: profiles/inkscape.json
- Create: profiles/birdbox.json
- Create: profiles/gimp.json
- Create: profiles/idle.json
- Create: tools/apply_compat.py
- Create: tests/test_apply_compat.py

**Interfaces:**
- Consumes: a materialized app workspace and profiles/<id>.json.
- Produces: apply_profile(root: Path, profile: dict) -> list[str]; it returns changed paths and raises ValueError when an expected anchor count differs.

- [ ] **Step 1: Write failing patch tests**

~~~python
# tests/test_apply_compat.py
import tempfile
import unittest
from pathlib import Path
from tools.apply_compat import apply_profile

class CompatibilityTests(unittest.TestCase):
    def test_replace_requires_exact_anchor_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build.gradle").write_text("jcenter()\njcenter()\n")
            profile = {"operations": [{
                "type": "replace", "path": "build.gradle",
                "old": "jcenter()", "new": "mavenCentral()", "count": 1
            }]}
            with self.assertRaisesRegex(ValueError, "expected 1 anchors, found 2"):
                apply_profile(root, profile)

    def test_replace_is_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build.gradle").write_text("jcenter()\n")
            profile = {"operations": [{
                "type": "replace", "path": "build.gradle",
                "old": "jcenter()", "new": "mavenCentral()", "count": 1
            }]}
            self.assertEqual(["build.gradle"], apply_profile(root, profile))
            self.assertEqual("mavenCentral()\n", (root / "build.gradle").read_text())

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Confirm the red state**

Run: python3 -m unittest tests.test_apply_compat -v  
Expected: ERROR because tools.apply_compat does not exist.

- [ ] **Step 3: Implement typed operations**

Support replace, delete_lines_matching, insert_after, set_xml_exported, and assert_absent. Resolve every path beneath the workspace and reject traversal. Every modifying operation declares an exact count. set_xml_exported accepts component tag/name pairs, sets android:exported=true only when absent, and rejects an existing false value.

- [ ] **Step 4: Encode shared FoxBox repairs in every applicable profile**

Profiles must conditionally cover jcenter to mavenCentral, sshlib 2.2.13 to 2.2.3, obsolete Termux publishing blocks, safe FreeRDP version discovery, required legacy ext properties, Build Tools 30.0.3 where the locked Gradle version requires it, and Android exported components. Profiles may use zero-count assertions when a newer launcher already contains the compatible form.

- [ ] **Step 5: Run profile unit and dry-run checks**

Run: python3 -m unittest tests.test_apply_compat -v  
Expected: 2 tests pass.

Run: for app in foxbox andacious gnuplot r libredocs devstudio inkscape birdbox gimp idle; do python3 tools/apply_compat.py --root apps/$app --profile profiles/$app.json --check; done  
Expected: all ten profiles report valid anchors without modifying apps/.

- [ ] **Step 6: Commit**

~~~bash
git add profiles tools/apply_compat.py tests/test_apply_compat.py
git commit -m "build: add isolated legacy compatibility profiles"
~~~

### Task 5: Isolated release build and signing

**Files:**
- Create: build-logic/signing.gradle
- Create: scripts/prepare_signing.sh
- Create: scripts/build_app.sh
- Create: tests/test_signing_contract.py
- Create: tests/test_build_contract.py

**Interfaces:**
- Consumes: app id, version code, version name, restored shared tree, and four signing environment variables.
- Produces: dist/<output_name> signed by the locked certificate; prepare_signing.sh prints only the keystore path and certificate fingerprint to GITHUB_OUTPUT.

- [ ] **Step 1: Write signing contract tests**

~~~python
# tests/test_signing_contract.py
import unittest
from pathlib import Path

class SigningContractTests(unittest.TestCase):
    def test_secret_values_are_not_logged(self):
        text = Path("scripts/prepare_signing.sh").read_text()
        self.assertNotIn("set -x", text)
        self.assertNotIn("echo $ANDROID_", text)

    def test_gradle_reads_environment_only(self):
        text = Path("build-logic/signing.gradle").read_text()
        for name in ("ANDROID_KEYSTORE_FILE", "ANDROID_KEYSTORE_PASSWORD",
                     "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD"):
            self.assertIn(f'System.getenv("{name}")', text)

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Confirm the red state**

Run: python3 -m unittest tests.test_signing_contract -v  
Expected: ERROR because signing files do not exist.

- [ ] **Step 3: Implement signing.gradle**

The fragment must throw GradleException when any signing environment value is blank, create signingConfigs.release from the four environment values, and assign it to buildTypes.release. No default value or debug keystore fallback is permitted.

- [ ] **Step 4: Implement prepare_signing.sh**

Decode ANDROID_KEYSTORE_BASE64 into RUNNER_TEMP/userland-apps-release.jks with umask 077. Use keytool -list with the alias and store password, require Entry type: PrivateKeyEntry, extract SHA256, and compare it to 82:9A:55:6F:C5:8A:D5:24:9B:5D:4C:4A:7F:CB:9A:96:9C:FF:38:26:AA:5C:7E:41:02:C3:13:B2:20:A4:5F:EC. Export ANDROID_KEYSTORE_FILE through GITHUB_ENV. Never print Base64 or passwords.

- [ ] **Step 5: Implement build_app.sh**

Validate the contract, find one app record by id, create an isolated RUNNER_TEMP/work-<id> directory, copy apps/<id>, copy the restored UserLAndLibrary into the workspace, apply the selected profile, copy signing.gradle, patch the root version properties to read ulaVersionCode and ulaVersionName Gradle properties, apply the signing fragment to app/build.gradle with an exact anchor, run Gradle configuration, then :app:assembleRelease with -PulaVersionCode and -PulaVersionName. Copy exactly one release APK to dist/<output_name>; fail on zero or multiple outputs.

- [ ] **Step 6: Run contract tests**

Run: python3 -m unittest tests.test_signing_contract tests.test_build_contract -v  
Expected: all tests pass.

- [ ] **Step 7: Build and verify one signed FoxBox APK**

Run: scripts/prepare_dependencies.sh dependencies.lock.json build/shared .cache/dependencies && scripts/prepare_signing.sh && scripts/build_app.sh foxbox 2000000001 2026.08.29.1  
Expected: dist/FoxBox.apk exists.

Run: apksigner verify --verbose --print-certs dist/FoxBox.apk  
Expected: verification succeeds and signer SHA-256 equals the locked fingerprint.

- [ ] **Step 8: Commit**

~~~bash
git add build-logic scripts/prepare_signing.sh scripts/build_app.sh tests/test_signing_contract.py tests/test_build_contract.py
git commit -m "build: add isolated signed release pipeline"
~~~

### Task 6: Ten-app GitHub Actions matrix

**Files:**
- Create: .github/workflows/ci.yml
- Create: tests/test_workflow_contract.py

**Interfaces:**
- Consumes: repository source plus the four Actions secrets.
- Produces: one signed APK artifact per matrix app and an aggregate required status.

- [ ] **Step 1: Write workflow structure tests**

~~~python
# tests/test_workflow_contract.py
import unittest
from pathlib import Path

class WorkflowContractTests(unittest.TestCase):
    def test_ci_contains_all_apps_and_no_secret_echo(self):
        text = Path(".github/workflows/ci.yml").read_text()
        for app in ("foxbox", "andacious", "gnuplot", "r", "libredocs",
                    "devstudio", "inkscape", "birdbox", "gimp", "idle"):
            self.assertIn(f"- {app}", text)
        self.assertNotIn("set -x", text)
        for secret in ("ANDROID_KEYSTORE_BASE64", "ANDROID_KEYSTORE_PASSWORD",
                       "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD"):
            self.assertIn(f"secrets.{secret}", text)

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Confirm the red state**

Run: python3 -m unittest tests.test_workflow_contract -v  
Expected: ERROR because ci.yml does not exist.

- [ ] **Step 3: Implement ci.yml**

Use pull_request, push to main, and workflow_dispatch. Set contents: read. Add a contract job on ubuntu-latest running python3 -m unittest discover -s tests -v and tools/validate_contract.py. Add a build matrix with fail-fast: false and the ten ids, JDK 17 for sdkmanager, Android platform 35 and Build Tools 35.0.0 plus legacy platform 31 and Build Tools 30.0.3. Select the Gradle JDK from the locked compatibility profile: JDK 11 for the historical FoxBox/legacy AGP profile and JDK 17 for launchers whose locked AGP requires it. Restore dependency and Gradle caches keyed from both lock files. Pass secrets only through step env, compute version code as 2000000000 + github.run_number, build, verify package/certificate with aapt and apksigner, and upload each APK with actions/upload-artifact@v4. Add aggregate job using if: always() that fails unless contract and build both succeeded.

- [ ] **Step 4: Run tests and a workflow syntax check**

Run: python3 -m unittest tests.test_workflow_contract -v  
Expected: tests pass.

Run: ruby -e "require 'yaml'; YAML.load_file('.github/workflows/ci.yml')"  
Expected: exit 0.

- [ ] **Step 5: Commit and observe the run**

~~~bash
git add .github/workflows/ci.yml tests/test_workflow_contract.py
git commit -m "ci: build and verify all UserLAnd APKs"
git push
~~~

Expected: contract job passes; record each matrix failure as evidence for the next compatibility correction rather than weakening validation.

### Task 7: Release metadata and publication

**Files:**
- Create: tools/release_manifest.py
- Create: tests/test_release_manifest.py
- Create: .github/workflows/release.yml

**Interfaces:**
- Consumes: dist/*.apk and sources.lock.json.
- Produces: dist/release-manifest.json and dist/SHA256SUMS; release.yml publishes exactly those files plus ten APKs.

- [ ] **Step 1: Write manifest tests**

~~~python
# tests/test_release_manifest.py
import tempfile
import unittest
from pathlib import Path
from tools.release_manifest import sha256_file, write_checksums

class ReleaseManifestTests(unittest.TestCase):
    def test_checksums_are_sorted_and_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "B.apk").write_bytes(b"b")
            (root / "A.apk").write_bytes(b"a")
            output = root / "SHA256SUMS"
            write_checksums(root, output)
            lines = output.read_text().splitlines()
            self.assertTrue(lines[0].endswith("  A.apk"))
            self.assertTrue(lines[1].endswith("  B.apk"))
            self.assertEqual(64, len(lines[0].split()[0]))

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Confirm the red state**

Run: python3 -m unittest tests.test_release_manifest -v  
Expected: ERROR because tools.release_manifest does not exist.

- [ ] **Step 3: Implement release inspection**

Use subprocess.run with check=True to call aapt dump badging and apksigner verify --print-certs. Parse package name, versionCode, versionName, sdkVersion, targetSdkVersion, and signer SHA-256. Reject missing/duplicate APKs, package mismatch, non-monotonic or out-of-range version codes, and certificate mismatch. Emit deterministic JSON with schema_version 1, release_tag, generated_at_utc, certificate_sha256, and an apps array sorted by id.

- [ ] **Step 4: Implement release.yml**

Trigger on tags matching v*. Set contents: write. Repeat the signed ten-app matrix rather than trusting expiring artifacts from another run. Upload each verified APK, download them in a publish job, run release_manifest.py, assert exactly ten APKs, then publish with gh release create "$GITHUB_REF_NAME" dist/* --verify-tag --generate-notes. Pass GH_TOKEN from github.token and never expose signing secrets to the publish job.

- [ ] **Step 5: Run tests**

Run: python3 -m unittest tests.test_release_manifest -v  
Expected: tests pass.

- [ ] **Step 6: Commit**

~~~bash
git add tools/release_manifest.py tests/test_release_manifest.py .github/workflows/release.yml
git commit -m "release: publish signed multi-app GitHub releases"
~~~

### Task 8: Emulator install, launch, upgrade, and user documentation

**Files:**
- Create: .github/workflows/upgrade-smoke.yml
- Create: scripts/emulator_smoke.sh
- Create: tests/test_emulator_contract.py
- Create: README.md

**Interfaces:**
- Consumes: two signed builds per app with version codes N and N+1.
- Produces: evidence that adb install, launcher start, and adb install -r upgrade succeed without signature conflicts.

- [ ] **Step 1: Write emulator command tests**

~~~python
# tests/test_emulator_contract.py
import unittest
from pathlib import Path

class EmulatorContractTests(unittest.TestCase):
    def test_smoke_script_installs_launches_and_upgrades(self):
        text = Path("scripts/emulator_smoke.sh").read_text()
        self.assertIn('adb install "$OLD_APK"', text)
        self.assertIn("android.intent.category.LAUNCHER", text)
        self.assertIn('adb install -r "$NEW_APK"', text)
        self.assertIn("dumpsys package", text)

if __name__ == "__main__":
    unittest.main()
~~~

- [ ] **Step 2: Confirm the red state**

Run: python3 -m unittest tests.test_emulator_contract -v  
Expected: ERROR because emulator_smoke.sh does not exist.

- [ ] **Step 3: Implement emulator_smoke.sh**

Accept package id, old APK, and new APK. Start with adb wait-for-device, uninstall the package if present, install the old APK, resolve the launcher using cmd package resolve-activity --brief, start it with monkey -p <package> -c android.intent.category.LAUNCHER 1, assert dumpsys package reports the old version, install -r the new APK, assert the new version is greater, and scan logcat for PackageManager signature mismatch or INSTALL_FAILED_UPDATE_INCOMPATIBLE. Always capture logcat and dumpsys evidence as artifacts.

- [ ] **Step 4: Implement upgrade-smoke.yml**

Use workflow_dispatch and a ten-app fail-fast:false matrix. Build N and N+1 with the same secrets, run a pinned Android emulator action at API 35, and invoke emulator_smoke.sh. Upload evidence even on failure. This workflow is required once before the first release and after any signing or package-name change.

- [ ] **Step 5: Write README.md**

Document the ten packages, source refs, build badge, latest Release link, Obtainium setup against the repository URL, certificate fingerprint, one-time uninstall requirement for publisher-signed installs, per-app completion status, runtime asset caveat, and exact local commands for contract tests. Do not call an app working until both its matrix build and upgrade-smoke entry pass.

- [ ] **Step 6: Run the complete local contract suite**

Run: python3 -m unittest discover -s tests -v && python3 tools/validate_contract.py  
Expected: all tests pass and Contract valid: 10 apps.

- [ ] **Step 7: Commit**

~~~bash
git add .github/workflows/upgrade-smoke.yml scripts/emulator_smoke.sh tests/test_emulator_contract.py README.md
git commit -m "test: verify install launch and signed upgrades"
~~~

### Task 9: First green build and release candidate

**Files:**
- Modify only the failing app profile, locked source ref, or shared compatibility code proven responsible by job logs.
- Update README.md status after evidence exists.

**Interfaces:**
- Consumes: CI and upgrade-smoke logs.
- Produces: ten green build entries, ten green upgrade entries, and a release tag whose assets pass release_manifest.py.

- [ ] **Step 1: Push the implementation and inspect every matrix result**

Run: git push origin main  
Expected: CI aggregate succeeds. If not, fetch the exact failed job log and reproduce that app locally before editing.

- [ ] **Step 2: Apply systematic per-app corrections**

For a shared dependency failure, add one shared failing test and fix shared logic. For an app-only failure, add a profile fixture test and edit only profiles/<id>.json. If a current launcher cannot be reconciled without behavior changes, walk its Git history newest-first, select the first publicly reproducible ancestor, update source_ref and SOURCE.json together, and document the exact failed API contract in the commit message and release notes.

- [ ] **Step 3: Re-run the full matrix after each correction batch**

Run: python3 -m unittest discover -s tests -v && python3 tools/validate_contract.py  
Expected: local suite passes before push; GitHub CI aggregate succeeds after push.

- [ ] **Step 4: Run the upgrade smoke workflow**

Run through GitHub Actions workflow_dispatch after CI is green.  
Expected: all ten matrix entries install, launch, and upgrade without signature conflicts.

- [ ] **Step 5: Create and verify the release candidate tag**

Run: git tag -a v2026.08.29-rc1 -m "UserLAnd Apps release candidate 1" && git push origin v2026.08.29-rc1  
Expected: release workflow succeeds and publishes ten APKs, SHA256SUMS, and release-manifest.json.

- [ ] **Step 6: Verify release assets independently**

Download the release assets, run sha256sum -c SHA256SUMS, run apksigner verify --verbose --print-certs on every APK, and compare every manifest package/version to release-manifest.json.  
Expected: all checks succeed and every signer fingerprint is the locked project certificate.

- [ ] **Step 7: Mark only evidenced apps complete**

Update README.md completion statuses using the CI run, upgrade-smoke run, and release URL as evidence. Commit with:

~~~bash
git add README.md
git commit -m "docs: record verified UserLAnd app release status"
git push origin main
~~~
