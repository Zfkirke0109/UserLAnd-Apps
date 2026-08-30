package tech.ula.library.utils

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.rauschig.jarchivelib.Archiver
import org.rauschig.jarchivelib.ArchiverFactory
import tech.ula.library.AssetDownloadService
import tech.ula.library.R
import tech.ula.library.model.repositories.DownloadMetadata
import tech.ula.library.model.repositories.LockedPayloadCatalog
import tech.ula.library.utils.preferences.AssetPreferences
import java.io.File
import java.io.IOException

sealed class AssetDownloadState
object CacheSyncAttemptedWhileCacheIsEmpty : AssetDownloadState()
object NonUserlandDownloadFound : AssetDownloadState()
object AllDownloadsCompletedSuccessfully : AssetDownloadState()
data class CompletedDownloadsUpdate(
    val numCompleted: Int,
    val numTotal: Int,
    val bytesWritten: Long = 0,
    val totalBytes: Long = 0
) : AssetDownloadState()

/**
 * A stalled setup the user can act on. [safeMessage] is shown to them, so it
 * describes the stage rather than quoting a server or a file path; [canRetry] is
 * false only when retrying cannot possibly help.
 */
data class AssetDownloadFailure(
    val reason: DownloadFailureLocalizationData,
    val safeMessage: String = "",
    val canRetry: Boolean = true
) : AssetDownloadState()

/**
 * Setup downloads, owned by the application rather than the OEM download provider.
 *
 * This is an adapter: the batch lives in [DownloadJournal], the transfers run in
 * [AssetDownloadService], and every question the state machine asks is answered by
 * reading the journal. Nothing depends on having received a particular broadcast,
 * which is what makes the answer the same whether the activity stayed up the whole
 * time or the process was recreated halfway through.
 */
class AssetDownloader(
    private val assetPreferences: AssetPreferences,
    private val ulaFiles: UlaFiles,
    private val context: Context
) {

    private val downloadDirectory = AssetDownloadService.downloadDirectory(context)
    private val journal = DownloadJournal(
        File(downloadDirectory, AssetDownloadService.JOURNAL_NAME)
    )
    private val catalog: LockedPayloadCatalog? by lazy { loadCatalog() }

    private var sessionId = UNKNOWN_ID
    private var filesystemId = UNKNOWN_ID

    /**
     * Remembered so the batch can name the session it belongs to. A process
     * recreated mid-download reads these back out of the journal instead of
     * dropping the user at selection again.
     */
    fun rememberSelection(sessionId: Long, filesystemId: Long) {
        if (sessionId != UNKNOWN_ID) this.sessionId = sessionId
        if (filesystemId != UNKNOWN_ID) this.filesystemId = filesystemId
    }

    fun cachedSessionId(): Long = journal.read()?.sessionId ?: UNKNOWN_ID

    fun cachedFilesystemId(): Long = journal.read()?.filesystemId ?: UNKNOWN_ID

    fun downloadStateHasBeenCached(): Boolean {
        val batch = journal.read() ?: return false
        return batch.state != DownloadBatchState.COMPLETE
    }

    fun syncStateWithCache(): AssetDownloadState {
        val batch = journal.read() ?: return CacheSyncAttemptedWhileCacheIsEmpty
        val reconciled = AssetDownloadPlanner.reconcile(batch)
        if (reconciled != batch) journal.write(reconciled)
        return asAssetDownloadState(AssetDownloadPlanner.outcomeOf(reconciled))
    }

    fun downloadRequirements(downloadRequirements: List<DownloadMetadata>) {
        val batch = AssetDownloadPlanner.plan(
            sessionId = sessionId,
            filesystemId = filesystemId,
            requirements = downloadRequirements.map { it.asRequirement() },
            downloadDirectory = downloadDirectory
        )
        journal.write(batch)
        assetPreferences.setDownloadsAreInProgress(inProgress = true)
        AssetDownloadService.enqueue(context)
    }

    /**
     * The identifier is only a nudge that something changed; the journal decides
     * what actually happened, so a signal that never arrived costs nothing.
     */
    fun handleDownloadComplete(downloadId: Long): AssetDownloadState {
        val batch = journal.read() ?: return NonUserlandDownloadFound
        val outcome = AssetDownloadPlanner.outcomeOf(batch)
        if (outcome is BatchSucceeded) {
            assetPreferences.setDownloadsAreInProgress(inProgress = false)
        }
        return asAssetDownloadState(outcome)
    }

    fun downloadIsForUserland(id: Long): Boolean = journal.read() != null

    /**
     * Runs the batch again, keeping everything already verified. Returns false when
     * there is no batch to retry, so the caller can restart setup instead.
     */
    fun retryDownloads(): Boolean {
        val batch = journal.read() ?: return false
        journal.write(AssetDownloadPlanner.retry(batch))
        assetPreferences.setDownloadsAreInProgress(inProgress = true)
        AssetDownloadService.enqueue(context)
        return true
    }

    /** Forgets the batch without touching the payloads it already verified. */
    fun discardBatch() {
        journal.clear()
        assetPreferences.setDownloadsAreInProgress(inProgress = false)
    }

    private fun asAssetDownloadState(outcome: BatchOutcome): AssetDownloadState {
        return when (outcome) {
            is BatchIdle -> CacheSyncAttemptedWhileCacheIsEmpty
            is BatchSucceeded -> AllDownloadsCompletedSuccessfully
            is BatchProgress -> CompletedDownloadsUpdate(
                outcome.completed, outcome.total, outcome.bytesWritten, outcome.totalBytes
            )
            is BatchFailed -> AssetDownloadFailure(
                DownloadFailureLocalizationData(
                    R.string.download_failure_http_error,
                    listOf(outcome.reason)
                ),
                safeMessage = outcome.reason,
                canRetry = true
            )
        }
    }

    private fun DownloadMetadata.asRequirement(): DownloadRequirement {
        // Default setup resolves exact bytes through the bundled catalog; a custom
        // filesystem source stays network-derived and is transferred unlocked.
        val locked = catalog?.payload(context.packageName, ulaFiles.getArchType(), filename)
        return DownloadRequirement(
            id = downloadTitle,
            filename = filename,
            url = locked?.url ?: url,
            expectedBytes = locked?.size ?: DownloadItem.UNKNOWN_LENGTH,
            sha256 = locked?.sha256 ?: ""
        )
    }

    private fun loadCatalog(): LockedPayloadCatalog? {
        return try {
            context.assets.open(CATALOG_ASSET).use { stream ->
                LockedPayloadCatalog.from(stream.readBytes().toString(Charsets.UTF_8))
            }
        } catch (err: IOException) {
            // A build without a rendered catalog falls back to network-derived
            // metadata rather than refusing to download anything at all.
            null
        }
    }

    @Throws(IOException::class)
    suspend fun prepareDownloadsForUse(
        archiverFactory: ArchiveFactoryWrapper = ArchiveFactoryWrapper()
    ) = withContext(Dispatchers.IO) {
        val stagingDirectory = File("${ulaFiles.filesDir.path}/staging")
        stagingDirectory.mkdirs()
        val downloadFiles = downloadDirectory.listFiles() ?: return@withContext
        downloadFiles.forEach {
            if (it.name.endsWith(".json") || it.name.endsWith(".part")) {
                return@forEach
            } else if (it.name.contains("rootfs.tar.gz")) {
                moveRootfsAssetInternal(it)
                return@forEach
            }
            extractAssets(it, stagingDirectory, archiverFactory)
        }
        stagingDirectory.deleteRecursively()
        journal.clear()
        assetPreferences.setDownloadsAreInProgress(inProgress = false)
    }

    private suspend fun moveRootfsAssetInternal(rootFsFile: File) = withContext(Dispatchers.IO) {
        val (repo, filename, version) = rootFsFile.name.split("-", limit = 4)
        val destinationDirectory = File("${ulaFiles.filesDir.absolutePath}/$repo")
        val target = File("${destinationDirectory.absolutePath}/$filename")

        destinationDirectory.mkdirs()

        // Clear old rootfs parts if they exist
        val directoryFiles = destinationDirectory.listFiles()
        directoryFiles?.let {
            for (file in directoryFiles) {
                if (file.name.contains("rootfs.tar.gz.part")) file.delete()
            }
        }

        rootFsFile.copyTo(target, overwrite = true)
        rootFsFile.delete()
        assetPreferences.setLatestDownloadFilesystemVersion(repo, version)
    }

    private suspend fun extractAssets(
        tarFile: File,
        stagingDirectory: File,
        archiverFactory: ArchiveFactoryWrapper
    ) = withContext(Dispatchers.IO) {
        val (repo, filename, version) = tarFile.name.split("-", limit = 3)
        val stagingTarget = File("${stagingDirectory.absolutePath}/$filename")
        val destination = File("${ulaFiles.filesDir.path}/$repo")

        tarFile.copyTo(stagingTarget, overwrite = true)
        tarFile.delete()

        val archiver = archiverFactory.createArchiver(stagingTarget)
        archiver.extract(stagingTarget, destination)
        val extractedFiles = destination.listFiles() ?: return@withContext
        for (file in extractedFiles) {
            ulaFiles.makePermissionsUsable(destination.absolutePath, file.name)
        }
        assetPreferences.setLatestDownloadVersion(repo, version)
    }

    companion object {
        const val UNKNOWN_ID = -1L
        const val CATALOG_ASSET = "r3-payloads.json"
    }
}

class ArchiveFactoryWrapper {
    fun createArchiver(archiverType: File): Archiver {
        return ArchiverFactory.createArchiver(archiverType)
    }
}
