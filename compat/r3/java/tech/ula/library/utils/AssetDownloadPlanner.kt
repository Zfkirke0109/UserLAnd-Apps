package tech.ula.library.utils

import java.io.File

/**
 * What the persisted batch says about setup right now, expressed without any
 * Android type so the decision itself can be exercised directly.
 */
sealed class BatchOutcome
object BatchIdle : BatchOutcome()
data class BatchProgress(
    val completed: Int,
    val total: Int,
    val bytesWritten: Long = 0,
    val totalBytes: Long = 0
) : BatchOutcome()
object BatchSucceeded : BatchOutcome()
data class BatchFailed(val reason: String, val itemId: String?) : BatchOutcome()

/** One asset setup requires, resolved from the locked catalog or a custom source. */
data class DownloadRequirement(
    val id: String,
    val filename: String,
    val url: String,
    val expectedBytes: Long = DownloadItem.UNKNOWN_LENGTH,
    val sha256: String = ""
)

/**
 * Turns download requirements into a durable batch and reads a batch back as the
 * state setup should be showing.
 *
 * All of it is a pure function of the journal, which is what lets a process that
 * was killed mid-download recover by reading state rather than by having received
 * every broadcast along the way.
 */
object AssetDownloadPlanner {

    fun plan(
        sessionId: Long,
        filesystemId: Long,
        requirements: List<DownloadRequirement>,
        downloadDirectory: File
    ): DownloadBatch {
        val items = requirements.map { requirement ->
            DownloadItem(
                id = requirement.id,
                url = requirement.url,
                destination = File(downloadDirectory, requirement.id).absolutePath,
                expectedBytes = requirement.expectedBytes,
                sha256 = requirement.sha256
            )
        }
        return DownloadBatch(
            sessionId = sessionId,
            filesystemId = filesystemId,
            items = items,
            state = if (items.isEmpty()) DownloadBatchState.COMPLETE else DownloadBatchState.PENDING
        )
    }

    /**
     * Reconciles the batch against the files actually on disk. A destination that
     * already exists at its full length is complete regardless of what the journal
     * last managed to record, which is how a batch interrupted after a publish but
     * before its journal write recovers without downloading the asset again.
     */
    fun reconcile(batch: DownloadBatch): DownloadBatch {
        var reconciled = batch
        batch.items.forEach { item ->
            if (item.state == DownloadItemState.COMPLETE) return@forEach
            val destination = item.destinationFile
            val complete = destination.exists() &&
                (item.expectedBytes == DownloadItem.UNKNOWN_LENGTH ||
                    destination.length() == item.expectedBytes)
            if (complete) {
                reconciled = reconciled.withItem(
                    item.copy(
                        bytesWritten = destination.length(),
                        state = DownloadItemState.COMPLETE,
                        error = null
                    )
                )
            }
        }
        return settle(reconciled)
    }

    fun outcomeOf(batch: DownloadBatch?): BatchOutcome {
        if (batch == null) return BatchIdle
        val failed = batch.items.firstOrNull { it.state == DownloadItemState.FAILED }
        if (failed != null) {
            return BatchFailed(failed.error ?: "The download did not finish.", failed.id)
        }
        if (batch.items.isNotEmpty() && batch.completedCount == batch.totalCount) {
            return BatchSucceeded
        }
        if (batch.items.isEmpty()) return BatchSucceeded
        return BatchProgress(
            batch.completedCount,
            batch.totalCount,
            batch.bytesWritten,
            batch.totalBytes
        )
    }

    /** The next asset to transfer, or null when the batch needs no more work. */
    fun nextPending(batch: DownloadBatch): DownloadItem? {
        if (batch.items.any { it.state == DownloadItemState.FAILED }) return null
        return batch.items.firstOrNull { it.state != DownloadItemState.COMPLETE }
    }

    fun applyResult(batch: DownloadBatch, result: TransferResult): DownloadBatch {
        val updated = when (result) {
            is TransferSucceeded -> result.item
            is TransferFailed ->
                if (result.terminal) {
                    result.item.copy(state = DownloadItemState.FAILED, error = result.reason)
                } else {
                    result.item.copy(state = DownloadItemState.IN_PROGRESS, error = result.reason)
                }
        }
        return settle(batch.withItem(updated))
    }

    /**
     * Prepares a failed batch to run again. Items that already completed keep their
     * bytes, so Retry costs the user only what is actually outstanding; the rest are
     * cleared of the previous attempt's error and its attempt count.
     */
    fun retry(batch: DownloadBatch): DownloadBatch {
        val items = batch.items.map { item ->
            if (item.state == DownloadItemState.COMPLETE) {
                item
            } else {
                item.copy(attempts = 0, state = DownloadItemState.PENDING, error = null)
            }
        }
        return settle(batch.copy(items = items))
    }

    private fun settle(batch: DownloadBatch): DownloadBatch {
        return when {
            batch.items.any { it.state == DownloadItemState.FAILED } ->
                batch.copy(state = DownloadBatchState.FAILED)
            batch.items.isNotEmpty() && batch.completedCount == batch.totalCount ->
                batch.copy(state = DownloadBatchState.COMPLETE)
            else -> batch.copy(state = DownloadBatchState.RUNNING)
        }
    }
}

/**
 * Whether a completion signal still concerns the batch we are running.
 *
 * The state machine accepts a completion event when it is either still
 * downloading or the signal is not ours; a signal that is neither leaves it in
 * IncorrectSessionTransition. Once a batch has been reported, the download
 * service can still emit a late signal, and the machine has moved on. Both
 * `downloadIsForUserland` and `handleDownloadComplete` read this one predicate
 * so they cannot disagree: if the signal is not ours the transition is allowed,
 * and the handler must then do nothing rather than re-announce an outcome the
 * machine has already acted on.
 */
fun signalBelongsToBatch(batch: DownloadBatch?, downloadsAreInProgress: Boolean): Boolean {
    return batch != null && downloadsAreInProgress
}
