package tech.ula.library

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import tech.ula.library.utils.AssetDownloadPlanner
import tech.ula.library.utils.AssetDownloadRunner
import tech.ula.library.utils.AssetDownloadSignals
import tech.ula.library.utils.BatchOutcome
import tech.ula.library.utils.BatchProgress
import tech.ula.library.utils.DownloadBatch
import tech.ula.library.utils.DownloadJournal
import tech.ula.library.utils.DownloadLifecycle
import tech.ula.library.utils.NotificationConstructor
import tech.ula.library.utils.ResumableAssetTransfer
import java.io.File
import kotlin.concurrent.thread

/**
 * Runs the setup downloads the application owns.
 *
 * Replacing the OEM download provider means the application is now responsible for
 * staying alive while transfers run, which is what the foreground notification
 * buys. Everything that decides what to fetch and what to record lives in
 * [AssetDownloadRunner]; this class supplies a thread, a notification, and the
 * process lifetime around it.
 */
class AssetDownloadService : Service() {

    private val notifications: NotificationConstructor by lazy { NotificationConstructor(this) }

    @Volatile private var running = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Foreground first: Android stops a background service that starts long
        // work, and the user is entitled to see a download this size running.
        notifications.createServiceNotificationChannel()
        startInForeground(buildNotification(BatchProgress(0, 0)))

        if (running) return START_STICKY
        running = true

        val journal = DownloadJournal(File(downloadDirectory(this), JOURNAL_NAME))
        val runner = AssetDownloadRunner(journal, ResumableAssetTransfer(), ServiceLifecycle())
        thread(name = "ula-asset-download") {
            try {
                runner.run()
            } finally {
                running = false
                stopForegroundCompat()
                stopSelf()
            }
        }
        return START_STICKY
    }

    private inner class ServiceLifecycle : DownloadLifecycle {
        override fun onStarted(batch: DownloadBatch) {
            AssetDownloadSignals.publish(AssetDownloadPlanner.outcomeOf(batch))
        }

        override fun onProgress(outcome: BatchOutcome) {
            startInForeground(buildNotification(outcome))
            AssetDownloadSignals.publish(outcome)
        }

        override fun onFinished(outcome: BatchOutcome) {
            AssetDownloadSignals.publish(outcome)
        }
    }

    // ServiceCompat's typed overloads only exist from androidx.core 1.7.0, and the
    // library pins 1.6.0, so these go straight to the platform behind version guards.
    private fun startInForeground(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun stopForegroundCompat() {
        @Suppress("DEPRECATION")
        stopForeground(true)
    }

    private fun buildNotification(outcome: BatchOutcome): Notification {
        val openApp = Intent(this, MainActivity::class.java)
        // FLAG_IMMUTABLE only exists from API 23 and the library still supports 21.
        val pendingFlags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }
        val pending = PendingIntent.getActivity(this, 0, openApp, pendingFlags)

        val builder = NotificationCompat.Builder(
            this, NotificationConstructor.serviceNotificationChannelId
        )
            .setSmallIcon(R.drawable.ic_stat_icon)
            .setContentTitle(getString(R.string.progress_downloading))
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setContentIntent(pending)

        if (outcome is BatchProgress && outcome.total > 0) {
            builder.setContentText(
                getString(R.string.progress_downloading_out_of, outcome.completed, outcome.total)
            )
            builder.setProgress(outcome.total, outcome.completed, false)
        } else {
            builder.setProgress(0, 0, true)
        }

        return builder.build()
    }

    companion object {
        const val NOTIFICATION_ID = 1001
        const val JOURNAL_NAME = "download-journal.json"

        /** Where transfers and their journal live, private to the application. */
        fun downloadDirectory(context: Context): File {
            return File(context.filesDir, "downloads").apply { mkdirs() }
        }

        fun enqueue(context: Context) {
            ContextCompat.startForegroundService(
                context, Intent(context, AssetDownloadService::class.java)
            )
        }
    }
}
