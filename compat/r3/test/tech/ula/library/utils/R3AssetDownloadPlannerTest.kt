package tech.ula.library.utils

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class R3AssetDownloadPlannerTest {

    @get:Rule val tempFolder = TemporaryFolder()

    private lateinit var downloadDirectory: File

    private val requirements = listOf(
        DownloadRequirement(
            id = "debian-assets.tar.gz-v7.7.9",
            filename = "assets.tar.gz",
            url = "https://example.invalid/assets.tar.gz",
            expectedBytes = 4096,
            sha256 = "aa".repeat(32)
        ),
        DownloadRequirement(
            id = "debian-rootfs.tar.gz-v7.7.9",
            filename = "rootfs.tar.gz",
            url = "https://example.invalid/rootfs.tar.gz",
            expectedBytes = 8192,
            sha256 = "bb".repeat(32)
        )
    )

    @Before
    fun setUp() {
        downloadDirectory = tempFolder.newFolder("downloads")
    }

    private fun plan() = AssetDownloadPlanner.plan(11, 5, requirements, downloadDirectory)

    @Test
    fun planCarriesTheSelectionContextAndLockedDigests() {
        val batch = plan()

        assertEquals(11L, batch.sessionId)
        assertEquals(5L, batch.filesystemId)
        assertEquals(2, batch.totalCount)
        assertEquals(0, batch.completedCount)
        assertEquals(
            File(downloadDirectory, "debian-rootfs.tar.gz-v7.7.9").absolutePath,
            batch.items[1].destination
        )
        assertEquals("bb".repeat(32), batch.items[1].sha256)
        assertTrue(batch.items.all { it.isLocked })
    }

    @Test
    fun anEmptyPlanIsAlreadyComplete() {
        val batch = AssetDownloadPlanner.plan(1, 1, emptyList(), downloadDirectory)

        assertEquals(DownloadBatchState.COMPLETE, batch.state)
        assertEquals(BatchSucceeded, AssetDownloadPlanner.outcomeOf(batch))
    }

    @Test
    fun anAbsentBatchIsIdleRatherThanFailed() {
        assertEquals(BatchIdle, AssetDownloadPlanner.outcomeOf(null))
    }

    @Test
    fun outcomeReportsProgressUntilEveryItemIsComplete() {
        var batch = plan()
        assertEquals(BatchProgress(0, 2), AssetDownloadPlanner.outcomeOf(batch))

        batch = batch.withItem(batch.items[0].copy(state = DownloadItemState.COMPLETE))
        assertEquals(BatchProgress(1, 2), AssetDownloadPlanner.outcomeOf(batch))

        batch = batch.withItem(batch.items[1].copy(state = DownloadItemState.COMPLETE))
        assertEquals(BatchSucceeded, AssetDownloadPlanner.outcomeOf(batch))
    }

    @Test
    fun aFailedItemFailsTheWholeBatchWithItsReason() {
        var batch = plan()
        batch = batch.withItem(
            batch.items[1].copy(state = DownloadItemState.FAILED, error = "checksum")
        )

        val outcome = AssetDownloadPlanner.outcomeOf(batch)

        assertTrue(outcome is BatchFailed)
        assertEquals("checksum", (outcome as BatchFailed).reason)
        assertEquals("debian-rootfs.tar.gz-v7.7.9", outcome.itemId)
    }

    @Test
    fun nextPendingWalksItemsInOrderAndStopsWhenDone() {
        var batch = plan()
        assertEquals("debian-assets.tar.gz-v7.7.9", AssetDownloadPlanner.nextPending(batch)!!.id)

        batch = batch.withItem(batch.items[0].copy(state = DownloadItemState.COMPLETE))
        assertEquals("debian-rootfs.tar.gz-v7.7.9", AssetDownloadPlanner.nextPending(batch)!!.id)

        batch = batch.withItem(batch.items[1].copy(state = DownloadItemState.COMPLETE))
        assertNull(AssetDownloadPlanner.nextPending(batch))
    }

    @Test
    fun nextPendingStopsOnceAnItemHasFailedTerminally() {
        val batch = plan().let {
            it.withItem(it.items[0].copy(state = DownloadItemState.FAILED, error = "404"))
        }

        // Continuing the batch past a terminal failure only wastes the user's data.
        assertNull(AssetDownloadPlanner.nextPending(batch))
    }

    @Test
    fun applyingASuccessAdvancesTheBatch() {
        val batch = plan()
        val done = batch.items[0].copy(state = DownloadItemState.COMPLETE, bytesWritten = 4096)

        val updated = AssetDownloadPlanner.applyResult(batch, TransferSucceeded(done))

        assertEquals(1, updated.completedCount)
        assertEquals(DownloadBatchState.RUNNING, updated.state)
    }

    @Test
    fun applyingTheLastSuccessCompletesTheBatch() {
        var batch = plan()
        batch = AssetDownloadPlanner.applyResult(
            batch, TransferSucceeded(batch.items[0].copy(state = DownloadItemState.COMPLETE))
        )
        batch = AssetDownloadPlanner.applyResult(
            batch, TransferSucceeded(batch.items[1].copy(state = DownloadItemState.COMPLETE))
        )

        assertEquals(DownloadBatchState.COMPLETE, batch.state)
        assertEquals(BatchSucceeded, AssetDownloadPlanner.outcomeOf(batch))
    }

    @Test
    fun applyingATerminalFailureFailsTheBatch() {
        val batch = plan()

        val updated = AssetDownloadPlanner.applyResult(
            batch, TransferFailed(batch.items[0], "The server answered 404.", terminal = true)
        )

        assertEquals(DownloadBatchState.FAILED, updated.state)
        assertTrue(AssetDownloadPlanner.outcomeOf(updated) is BatchFailed)
    }

    @Test
    fun applyingARetryableFailureKeepsTheBatchRunnable() {
        val batch = plan()

        val updated = AssetDownloadPlanner.applyResult(
            batch,
            TransferFailed(
                batch.items[0].copy(bytesWritten = 100),
                "The download was interrupted.",
                terminal = false
            )
        )

        assertEquals(DownloadBatchState.RUNNING, updated.state)
        assertEquals("debian-assets.tar.gz-v7.7.9", AssetDownloadPlanner.nextPending(updated)!!.id)
        assertEquals(100L, updated.items[0].bytesWritten)
    }

    @Test
    fun reconcileAdoptsAnAssetAlreadyPublishedBeforeTheJournalWasWritten() {
        val batch = plan()
        // Killed between the publishing rename and the journal write.
        File(batch.items[0].destination).writeBytes(ByteArray(4096))

        val reconciled = AssetDownloadPlanner.reconcile(batch)

        assertEquals(1, reconciled.completedCount)
        assertEquals(4096L, reconciled.items[0].bytesWritten)
        assertEquals("debian-rootfs.tar.gz-v7.7.9", AssetDownloadPlanner.nextPending(reconciled)!!.id)
    }

    @Test
    fun reconcileIgnoresAShortFileOnDisk() {
        val batch = plan()
        File(batch.items[0].destination).writeBytes(ByteArray(10))

        val reconciled = AssetDownloadPlanner.reconcile(batch)

        assertEquals(0, reconciled.completedCount)
        assertEquals("debian-assets.tar.gz-v7.7.9", AssetDownloadPlanner.nextPending(reconciled)!!.id)
    }

    @Test
    fun reconcileCompletesABatchWhoseAssetsAreAllAlreadyOnDisk() {
        val batch = plan()
        File(batch.items[0].destination).writeBytes(ByteArray(4096))
        File(batch.items[1].destination).writeBytes(ByteArray(8192))

        val reconciled = AssetDownloadPlanner.reconcile(batch)

        assertEquals(DownloadBatchState.COMPLETE, reconciled.state)
        assertEquals(BatchSucceeded, AssetDownloadPlanner.outcomeOf(reconciled))
    }
}
