package tech.ula.library.utils

import android.Manifest
import android.annotation.TargetApi
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.core.content.ContextCompat
import tech.ula.customlibrary.BuildConfig
import tech.ula.library.R

class PermissionHandler {
    companion object {
        private const val permissionRequestCode = 1234
        private var pendingAllFilesAccessRequest = false

        private fun runtimePermissions(forSession: Boolean): Array<String> {
            val required = mutableListOf<String>()
            if (Build.VERSION.SDK_INT in Build.VERSION_CODES.M..Build.VERSION_CODES.Q) {
                required += Manifest.permission.READ_EXTERNAL_STORAGE
                required += Manifest.permission.WRITE_EXTERNAL_STORAGE
            }
            if (forSession && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                required += Manifest.permission.POST_NOTIFICATIONS
            }
            if (forSession && BuildConfig.USES_MICROPHONE) {
                required += Manifest.permission.RECORD_AUDIO
            }
            return required.distinct().toTypedArray()
        }

        private fun deniedRuntimePermissions(
            context: Context,
            forSession: Boolean
        ): Array<String> = runtimePermissions(forSession).filter {
            ContextCompat.checkSelfPermission(context, it) !=
                    PackageManager.PERMISSION_GRANTED
        }.toTypedArray()

        private fun needsAllFilesAccess(forSession: Boolean): Boolean {
            return forSession &&
                    Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
                    !Environment.isExternalStorageManager()
        }

        fun permissionsAreGranted(context: Context, forSession: Boolean): Boolean {
            return deniedRuntimePermissions(context, forSession).isEmpty() &&
                    !needsAllFilesAccess(forSession)
        }

        fun permissionsWereGranted(
            requestCode: Int,
            permissions: Array<out String>,
            grantResults: IntArray
        ): Boolean {
            return requestCode == permissionRequestCode &&
                    permissions.size == grantResults.size &&
                    grantResults.indices.all {
                        grantResults[it] == PackageManager.PERMISSION_GRANTED
                    }
        }

        fun showPermissionsNecessaryDialog(activity: Activity, forSession: Boolean) {
            if (permissionsAreGranted(activity, forSession)) return
            AlertDialog.Builder(activity)
                    .setMessage(
                        activity.getString(
                            R.string.alert_permissions_necessary_message,
                            activity.getString(R.string.app_name)
                        )
                    )
                    .setTitle(
                        activity.getString(
                            R.string.alert_permissions_necessary_title,
                            activity.getString(R.string.app_name)
                        )
                    )
                    .setPositiveButton(R.string.button_ok) { dialog, _ ->
                        requestNecessaryPermissions(activity, forSession)
                        dialog.dismiss()
                    }
                    .setNegativeButton(
                        R.string.alert_permissions_necessary_cancel_button
                    ) { dialog, _ ->
                        dialog.dismiss()
                    }
                    .create()
                    .show()
        }

        fun requestNecessaryPermissions(activity: Activity, forSession: Boolean) {
            val runtimePermissions = deniedRuntimePermissions(activity, forSession)
            if (runtimePermissions.isNotEmpty()) {
                activity.requestPermissions(runtimePermissions, permissionRequestCode)
                return
            }
            if (needsAllFilesAccess(forSession)) {
                openAllFilesAccessSettings(activity)
            }
        }

        @TargetApi(Build.VERSION_CODES.R)
        private fun openAllFilesAccessSettings(activity: Activity) {
            pendingAllFilesAccessRequest = true
            val appIntent = Intent(
                Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                Uri.parse("package:${activity.packageName}")
            )
            try {
                activity.startActivity(appIntent)
            } catch (appPageMissing: ActivityNotFoundException) {
                try {
                    activity.startActivity(
                        Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                    )
                } catch (settingsMissing: ActivityNotFoundException) {
                    pendingAllFilesAccessRequest = false
                }
            }
        }

        fun consumeAllFilesAccessRequest(): Boolean {
            val pending = pendingAllFilesAccessRequest
            pendingAllFilesAccessRequest = false
            return pending
        }
    }
}
