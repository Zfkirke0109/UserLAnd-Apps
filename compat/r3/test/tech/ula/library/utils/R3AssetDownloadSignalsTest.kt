package tech.ula.library.utils

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class R3AssetDownloadSignalsTest {

    @Before
    fun setUp() = AssetDownloadSignals.reset()

    @After
    fun tearDown() = AssetDownloadSignals.reset()

    @Test
    fun observersReceiveEveryPublishedOutcomeInOrder() {
        val seen = mutableListOf<BatchOutcome>()
        AssetDownloadSignals.observe { seen.add(it) }

        AssetDownloadSignals.publish(BatchProgress(0, 2))
        AssetDownloadSignals.publish(BatchProgress(1, 2))
        AssetDownloadSignals.publish(BatchSucceeded)

        assertEquals(listOf(BatchProgress(0, 2), BatchProgress(1, 2), BatchSucceeded), seen)
    }

    @Test
    fun everyObserverIsNotified() {
        val first = mutableListOf<BatchOutcome>()
        val second = mutableListOf<BatchOutcome>()
        AssetDownloadSignals.observe { first.add(it) }
        AssetDownloadSignals.observe { second.add(it) }

        AssetDownloadSignals.publish(BatchSucceeded)

        assertEquals(listOf(BatchSucceeded), first)
        assertEquals(listOf(BatchSucceeded), second)
    }

    @Test
    fun aCancelledObserverStopsReceiving() {
        val seen = mutableListOf<BatchOutcome>()
        val registration = AssetDownloadSignals.observe { seen.add(it) }

        AssetDownloadSignals.publish(BatchProgress(0, 1))
        registration.cancel()
        AssetDownloadSignals.publish(BatchSucceeded)

        assertEquals(listOf(BatchProgress(0, 1)), seen)
    }

    @Test
    fun theLatestOutcomeIsReadableWithoutHavingObserved() {
        // A screen recreated mid-download reads state rather than replaying signals.
        AssetDownloadSignals.publish(BatchProgress(1, 3))

        assertEquals(BatchProgress(1, 3), AssetDownloadSignals.latest)
    }

    @Test
    fun aListenerRegisteringAfterTheBatchFinishedStillHearsAboutIt() {
        // Release run 4: the rootfs took minutes, the activity was recreated
        // while it downloaded, and the new listener registered after the batch
        // was already complete. Nothing publishes again, so setup waited for a
        // signal that had been and gone.
        AssetDownloadSignals.publish(BatchSucceeded)

        val heard = mutableListOf<BatchOutcome>()
        AssetDownloadSignals.observe { outcome -> heard.add(outcome) }

        assertEquals(listOf<BatchOutcome>(BatchSucceeded), heard)
    }

    @Test
    fun aFailedBatchIsReplayedToo() {
        AssetDownloadSignals.publish(BatchFailed("checksum", "rootfs"))

        val heard = mutableListOf<BatchOutcome>()
        AssetDownloadSignals.observe { outcome -> heard.add(outcome) }

        assertEquals(listOf<BatchOutcome>(BatchFailed("checksum", "rootfs")), heard)
    }

    @Test
    fun anIdleRegistryTellsAListenerNothing() {
        // Nothing has happened yet, so there is nothing to replay.
        val heard = mutableListOf<BatchOutcome>()
        AssetDownloadSignals.observe { outcome -> heard.add(outcome) }

        assertEquals(emptyList<BatchOutcome>(), heard)
    }

    @Test
    fun latestStartsIdleAndResets() {
        assertEquals(BatchIdle, AssetDownloadSignals.latest)

        AssetDownloadSignals.publish(BatchSucceeded)
        AssetDownloadSignals.reset()

        assertEquals(BatchIdle, AssetDownloadSignals.latest)
    }

    @Test
    fun publishingWithNoObserversIsHarmless() {
        AssetDownloadSignals.publish(BatchFailed("checksum", "rootfs"))

        assertEquals(BatchFailed("checksum", "rootfs"), AssetDownloadSignals.latest)
    }
}
