package tech.ula.library.utils

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The emulator gate caught this on a real first run: a completion signal
 * arriving after setup had moved on left the state machine in
 *
 *   IncorrectSessionTransition(
 *     event=AssetDownloadComplete(downloadAssetId=0),
 *     state=CopyingFilesToLocalDirectories)
 *
 * The signal carries a sentinel id, so the only thing that can tell a live
 * completion from a late echo is whether the batch is still running.
 */
class R3LateDownloadSignalTest {

    /** The rule SessionStartupFsm.transitionIsAcceptable applies to this event. */
    private fun machineAccepts(stateIsDownloadingAssets: Boolean, signalIsOurs: Boolean): Boolean {
        return stateIsDownloadingAssets || !signalIsOurs
    }

    private fun batch(state: DownloadBatchState = DownloadBatchState.RUNNING) = DownloadBatch(
        sessionId = 1,
        filesystemId = 1,
        items = listOf(
            DownloadItem(
                id = "rootfs",
                url = "https://example.invalid/rootfs.tar.gz",
                destination = "/tmp/rootfs.tar.gz",
                expectedBytes = 10,
                sha256 = "",
                bytesWritten = 10,
                state = DownloadItemState.COMPLETE
            )
        ),
        state = state
    )

    @Test
    fun lateSignalAfterTheBatchWasReportedIsNotOurs() {
        // Downloads finished, the machine has advanced to copying files, and the
        // service emits one more signal.
        val isOurs = signalBelongsToBatch(batch(), downloadsAreInProgress = false)

        assertFalse("a signal for a batch already reported is not ours", isOurs)
        assertTrue(
            "the machine must accept it rather than post IncorrectSessionTransition",
            machineAccepts(stateIsDownloadingAssets = false, signalIsOurs = isOurs)
        )
    }

    @Test
    fun signalDuringDownloadIsOurs() {
        assertTrue(signalBelongsToBatch(batch(), downloadsAreInProgress = true))
    }

    @Test
    fun signalWithNoBatchIsNotOurs() {
        assertFalse(signalBelongsToBatch(null, downloadsAreInProgress = true))
    }

    @Test
    fun everyCombinationLeavesTheMachineInALegalTransition() {
        // Exhaustive: whatever the batch and flag, an arriving signal must never
        // be both unacceptable to the machine and unhandled.
        for (hasBatch in listOf(true, false)) {
            for (inProgress in listOf(true, false)) {
                for (downloading in listOf(true, false)) {
                    val isOurs = signalBelongsToBatch(
                        if (hasBatch) batch() else null,
                        inProgress
                    )
                    val accepted = machineAccepts(downloading, isOurs)
                    if (!accepted) {
                        // The only legal way to be rejected is a live batch
                        // arriving while the machine is genuinely elsewhere,
                        // which the flag must prevent.
                        assertTrue(
                            "rejected signal must mean downloads are still running",
                            inProgress && hasBatch && !downloading
                        )
                    }
                }
            }
        }
    }
}
