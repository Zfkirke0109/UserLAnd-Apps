package tech.ula.library.utils

/**
 * The host that owns the user-visible side of a batch. The service implements it
 * with a foreground notification; tests implement it to observe ordering.
 */
interface DownloadLifecycle {
    /** Called before any network work begins. */
    fun onStarted(batch: DownloadBatch)

    fun onProgress(outcome: BatchOutcome)

    /** Called once, after the batch reaches a terminal outcome. */
    fun onFinished(outcome: BatchOutcome)
}

/**
 * Drives one batch to a terminal outcome, journaling after every network boundary.
 *
 * The loop is deliberately free of Android types: what makes the download reliable
 * is the order of the steps and what is durable at each one, and that is worth
 * being able to exercise directly. The service around it only supplies the
 * foreground notification and a thread.
 */
class AssetDownloadRunner(
    private val journal: DownloadJournal,
    private val transfer: ResumableAssetTransfer,
    private val lifecycle: DownloadLifecycle
) {

    fun run(): BatchOutcome {
        val stored = journal.read() ?: run {
            val idle = BatchIdle
            lifecycle.onFinished(idle)
            return idle
        }

        // Adopt anything already published, then record that reconciliation before
        // going near the network so a crash here cannot lose completed work.
        var batch = AssetDownloadPlanner.reconcile(stored)
        journal.write(batch)

        lifecycle.onStarted(batch)
        lifecycle.onProgress(AssetDownloadPlanner.outcomeOf(batch))

        while (true) {
            val pending = AssetDownloadPlanner.nextPending(batch) ?: break

            val result = transfer.transfer(pending) { written, _ ->
                latestBytes = written
            }

            batch = AssetDownloadPlanner.applyResult(batch, result)
            // Durable before it is announced: a listener must never learn of
            // progress the journal could not survive a restart to confirm.
            journal.write(batch)
            lifecycle.onProgress(AssetDownloadPlanner.outcomeOf(batch))

            if (result is TransferFailed && result.terminal) break
        }

        val outcome = AssetDownloadPlanner.outcomeOf(batch)
        if (outcome is BatchSucceeded) {
            journal.write(batch.copy(state = DownloadBatchState.COMPLETE))
        }
        lifecycle.onFinished(outcome)
        return outcome
    }

    /** Most recent byte count observed, exposed for the notification's progress. */
    @Volatile var latestBytes: Long = 0
        private set
}
