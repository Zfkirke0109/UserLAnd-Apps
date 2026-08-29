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
