package tech.ula.library.utils

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class R3DownloadJournalTest {

    @get:Rule val tempFolder = TemporaryFolder()

    private lateinit var journalFile: File
    private lateinit var journal: DownloadJournal

    @Before
    fun setUp() {
        journalFile = File(tempFolder.newFolder("downloads"), "journal.json")
        journal = DownloadJournal(journalFile)
    }

    private fun batch(state: DownloadBatchState = DownloadBatchState.RUNNING) = DownloadBatch(
        sessionId = 42,
        filesystemId = 7,
        state = state,
        items = listOf(
            DownloadItem(
                id = "assets",
                url = "https://example.invalid/assets.tar.gz",
                destination = "/data/downloads/assets.tar.gz",
                expectedBytes = 1024,
                sha256 = "aa".repeat(32),
                bytesWritten = 512,
                attempts = 2,
                state = DownloadItemState.IN_PROGRESS,
                error = "The download was interrupted."
            ),
            DownloadItem(
                id = "rootfs",
                url = "https://example.invalid/rootfs.tar.gz",
                destination = "/data/downloads/rootfs.tar.gz",
                expectedBytes = 2048,
                sha256 = "bb".repeat(32)
            )
        )
    )

    @Test
    fun interruptedJournalReloadKeepsSessionAndFilesystemIds() {
        journal.write(batch())

        // A recreated process reads the journal through a brand new instance.
        val reloaded = DownloadJournal(journalFile).read()

        assertNotNull(reloaded)
        assertEquals(42L, reloaded!!.sessionId)
        assertEquals(7L, reloaded.filesystemId)
        assertEquals(DownloadBatchState.RUNNING, reloaded.state)
    }

    @Test
    fun reloadPreservesEveryItemFieldIncludingResumeOffset() {
        journal.write(batch())

        val reloaded = DownloadJournal(journalFile).read()!!

        assertEquals(batch().items, reloaded.items)
        val interrupted = reloaded.items.first { it.id == "assets" }
        assertEquals(512L, interrupted.bytesWritten)
        assertEquals(2, interrupted.attempts)
        assertEquals(DownloadItemState.IN_PROGRESS, interrupted.state)
        assertEquals("The download was interrupted.", interrupted.error)
    }

    @Test
    fun absentJournalReadsAsNothingInProgress() {
        assertNull(journal.read())
    }

    @Test
    fun truncatedJournalIsTreatedAsAbsentRatherThanResumedBadly() {
        journal.write(batch())
        val complete = journalFile.readText()
        journalFile.writeText(complete.substring(0, complete.length / 2))

        // Resuming from a half-written offset would corrupt the transfer.
        assertNull(DownloadJournal(journalFile).read())
    }

    @Test
    fun emptyJournalIsTreatedAsAbsent() {
        journalFile.parentFile.mkdirs()
        journalFile.writeText("")

        assertNull(journal.read())
    }

    @Test
    fun writeReplacesAnEarlierBatchAndLeavesNoTemporaryFile() {
        journal.write(batch())
        journal.write(batch(state = DownloadBatchState.COMPLETE))

        assertEquals(DownloadBatchState.COMPLETE, journal.read()!!.state)
        assertFalse(File("${journalFile.absolutePath}.tmp").exists())
    }

    @Test
    fun clearRemovesTheJournalAndAnyTemporaryFile() {
        journal.write(batch())
        File("${journalFile.absolutePath}.tmp").writeText("stale")

        journal.clear()

        assertFalse(journalFile.exists())
        assertFalse(File("${journalFile.absolutePath}.tmp").exists())
        assertNull(journal.read())
    }

    @Test
    fun withItemReplacesOnlyTheNamedItem() {
        val original = batch()
        val updated = original.items.first().copy(
            bytesWritten = 1024,
            state = DownloadItemState.COMPLETE
        )

        val result = original.withItem(updated)

        assertEquals(DownloadItemState.COMPLETE, result.items.first().state)
        assertEquals(1024L, result.items.first().bytesWritten)
        assertEquals(original.items[1], result.items[1])
    }

    @Test
    fun batchCountsCompletedItems() {
        val original = batch()
        assertEquals(0, original.completedCount)
        assertEquals(2, original.totalCount)

        val advanced = original.withItem(
            original.items.first().copy(state = DownloadItemState.COMPLETE)
        )

        assertEquals(1, advanced.completedCount)
        assertEquals(2, advanced.totalCount)
    }

    @Test
    fun unknownFieldsInAnOlderJournalAreSkipped() {
        journalFile.parentFile.mkdirs()
        journalFile.writeText(
            """
            {"schema_version":1,"session_id":9,"filesystem_id":3,"state":"RUNNING",
             "unexpected":{"nested":true},
             "items":[{"id":"a","url":"https://example.invalid/a","destination":"/tmp/a",
                       "expected_bytes":1,"sha256":"","bytes_written":0,"attempts":0,
                       "state":"PENDING","error":null,"future_field":42}]}
            """.trimIndent()
        )

        val reloaded = journal.read()

        assertNotNull(reloaded)
        assertEquals(9L, reloaded!!.sessionId)
        assertEquals(1, reloaded.items.size)
        assertEquals("a", reloaded.items.first().id)
    }

    @Test
    fun anItemCarriesItsPartFileBesideItsDestination() {
        val item = batch().items.first()

        assertEquals("/data/downloads/assets.tar.gz.part", item.partFile.absolutePath)
        assertEquals("/data/downloads/assets.tar.gz", item.destinationFile.absolutePath)
        assertTrue(item.isLocked)
        assertFalse(item.copy(sha256 = "").isLocked)
    }
}
