package tech.ula.library.utils

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Release run 4 stranded every job here. The 307MB rootfs downloaded in full
 * -- the journal snapshot records 307175937/307175937, attempts 6, COMPLETE --
 * and setup never left DownloadingAssets, so extraction never started and the
 * gate waited out its full half hour.
 *
 * The completion signal is delivered in process. A download that takes minutes
 * can finish while nothing is listening, and the only recovery is the sync the
 * machine performs when it resumes.
 */
class R3StrandedBatchTest {

    private fun batch(state: DownloadBatchState) = DownloadBatch(
        sessionId = 1,
        filesystemId = 1,
        items = listOf(
            DownloadItem(
                id = "rootfs",
                url = "https://example.invalid/rootfs.tar.gz",
                destination = "/tmp/rootfs.tar.gz",
                expectedBytes = 307175937,
                sha256 = "",
                bytesWritten = 307175937,
                state = DownloadItemState.COMPLETE
            )
        ),
        state = state
    )

    @Test
    fun aFinishedBatchIsStillWorthSyncing() {
        // The case that stranded the run: everything downloaded, nothing
        // listening when it finished.
        assertTrue(hasCachedStateToSync(batch(DownloadBatchState.COMPLETE)))
    }

    @Test
    fun anUnfinishedBatchIsWorthSyncing() {
        assertTrue(hasCachedStateToSync(batch(DownloadBatchState.RUNNING)))
        assertTrue(hasCachedStateToSync(batch(DownloadBatchState.PENDING)))
        assertTrue(hasCachedStateToSync(batch(DownloadBatchState.FAILED)))
    }

    @Test
    fun nothingToSyncOnceTheBatchHasBeenActedOnAndCleared() {
        // Staging clears the journal, and that absence is what ends the sync.
        assertFalse(hasCachedStateToSync(null))
    }

    @Test
    fun aSyncedCompleteBatchReportsSuccessSoTheMachineCanAdvance() {
        // Syncing has to yield the outcome that moves setup on to copying and
        // extracting, not merely report that a batch exists.
        assertTrue(AssetDownloadPlanner.outcomeOf(batch(DownloadBatchState.COMPLETE)) is BatchSucceeded)
    }
}
