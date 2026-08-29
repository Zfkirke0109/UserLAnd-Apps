package tech.ula.library.utils

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class R3AssetDownloadRunnerTest {

    @get:Rule val tempFolder = TemporaryFolder()

    private lateinit var server: MockWebServer
    private lateinit var downloadDirectory: File
    private lateinit var journal: DownloadJournal
    private lateinit var runner: AssetDownloadRunner
    private lateinit var lifecycle: RecordingLifecycle

    private val assetsBody = "assets payload"
    private val rootfsBody = "rootfs payload body"

    /** Records the order of lifecycle callbacks against the requests the server saw. */
    private inner class RecordingLifecycle : DownloadLifecycle {
        val events = mutableListOf<String>()
        val progress = mutableListOf<BatchOutcome>()
        var finished: BatchOutcome? = null
        var requestsAtStart = -1

        override fun onStarted(batch: DownloadBatch) {
            requestsAtStart = server.requestCount
            events.add("started")
        }

        override fun onProgress(outcome: BatchOutcome) {
            events.add("progress")
            progress.add(outcome)
        }

        override fun onFinished(outcome: BatchOutcome) {
            events.add("finished")
            finished = outcome
        }
    }

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        downloadDirectory = tempFolder.newFolder("downloads")
        journal = DownloadJournal(File(downloadDirectory, "journal.json"))
        lifecycle = RecordingLifecycle()
        runner = AssetDownloadRunner(
            journal,
            ResumableAssetTransfer(
                OkHttpClient.Builder()
                    .connectTimeout(2, TimeUnit.SECONDS)
                    .readTimeout(2, TimeUnit.SECONDS)
                    .build()
            ),
            lifecycle
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun sha256Of(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray())
            .joinToString("") { "%02x".format(it) }

    private fun writePlan(): DownloadBatch {
        val batch = AssetDownloadPlanner.plan(
            sessionId = 11,
            filesystemId = 5,
            requirements = listOf(
                DownloadRequirement(
                    "assets", "assets.tar.gz", server.url("/assets").toString(),
                    assetsBody.toByteArray().size.toLong(), sha256Of(assetsBody)
                ),
                DownloadRequirement(
                    "rootfs", "rootfs.tar.gz", server.url("/rootfs").toString(),
                    rootfsBody.toByteArray().size.toLong(), sha256Of(rootfsBody)
                )
            ),
            downloadDirectory = downloadDirectory
        )
        journal.write(batch)
        return batch
    }

    @Test
    fun entersTheForegroundBeforeAnyTransferBegins() {
        writePlan()
        server.enqueue(MockResponse().setBody(assetsBody))
        server.enqueue(MockResponse().setBody(rootfsBody))

        runner.run()

        assertEquals("started", lifecycle.events.first())
        assertEquals("no request may precede the foreground start", 0, lifecycle.requestsAtStart)
    }

    @Test
    fun completesEveryItemAndFinishesOnce() {
        writePlan()
        server.enqueue(MockResponse().setBody(assetsBody))
        server.enqueue(MockResponse().setBody(rootfsBody))

        val outcome = runner.run()

        assertEquals(BatchSucceeded, outcome)
        assertEquals(BatchSucceeded, lifecycle.finished)
        assertEquals(1, lifecycle.events.count { it == "finished" })
        assertEquals("finished", lifecycle.events.last())
        assertEquals(assetsBody, File(downloadDirectory, "assets").readText())
        assertEquals(rootfsBody, File(downloadDirectory, "rootfs").readText())
    }

    @Test
    fun progressIsReportedForEachCompletedItem() {
        writePlan()
        server.enqueue(MockResponse().setBody(assetsBody))
        server.enqueue(MockResponse().setBody(rootfsBody))

        runner.run()

        assertEquals(
            listOf(BatchProgress(0, 2), BatchProgress(1, 2), BatchSucceeded),
            lifecycle.progress
        )
    }

    @Test
    fun everyAnnouncedStateIsAlreadyDurable() {
        writePlan()
        server.enqueue(MockResponse().setBody(assetsBody))
        server.enqueue(MockResponse().setBody(rootfsBody))
        val durable = mutableListOf<BatchOutcome>()

        val checking = AssetDownloadRunner(
            journal,
            ResumableAssetTransfer(OkHttpClient()),
            object : DownloadLifecycle {
                override fun onStarted(batch: DownloadBatch) = Unit
                override fun onProgress(outcome: BatchOutcome) {
                    // Whatever a listener is told must survive a restart right now.
                    durable.add(AssetDownloadPlanner.outcomeOf(DownloadJournal(File(downloadDirectory, "journal.json")).read()))
                }
                override fun onFinished(outcome: BatchOutcome) = Unit
            }
        )
        checking.run()

        assertEquals(listOf(BatchProgress(0, 2), BatchProgress(1, 2), BatchSucceeded), durable)
    }

    @Test
    fun aTerminalFailureStopsTheBatchAndIsReported() {
        writePlan()
        server.enqueue(MockResponse().setResponseCode(404))

        val outcome = runner.run()

        assertTrue(outcome is BatchFailed)
        assertTrue(lifecycle.finished is BatchFailed)
        assertEquals("the second asset must not be requested", 1, server.requestCount)
        assertFalse(File(downloadDirectory, "rootfs").exists())
    }

    @Test
    fun aFailedBatchStaysFailedAcrossARestart() {
        writePlan()
        server.enqueue(MockResponse().setResponseCode(404))
        runner.run()

        val reloaded = DownloadJournal(File(downloadDirectory, "journal.json")).read()

        assertEquals(DownloadBatchState.FAILED, reloaded!!.state)
        assertTrue(AssetDownloadPlanner.outcomeOf(reloaded) is BatchFailed)
    }

    @Test
    fun aRestartResumesWithoutRefetchingCompletedAssets() {
        writePlan()
        server.enqueue(MockResponse().setBody(assetsBody))
        server.enqueue(MockResponse().setResponseCode(404))
        runner.run()
        assertEquals(2, server.requestCount)

        // A new process, a new runner, the same journal on disk.
        val second = RecordingLifecycle()
        val resumed = AssetDownloadRunner(
            DownloadJournal(File(downloadDirectory, "journal.json")),
            ResumableAssetTransfer(OkHttpClient()),
            second
        )
        val outcome = resumed.run()

        // The batch already failed terminally, so nothing more is fetched.
        assertTrue(outcome is BatchFailed)
        assertEquals(2, server.requestCount)
        assertEquals(assetsBody, File(downloadDirectory, "assets").readText())
    }

    @Test
    fun anAssetPublishedBeforeTheJournalWasWrittenIsNotFetchedAgain() {
        val batch = writePlan()
        // Killed between the publishing rename and the journal write.
        File(batch.items[0].destination).writeText(assetsBody)
        server.enqueue(MockResponse().setBody(rootfsBody))

        val outcome = runner.run()

        assertEquals(BatchSucceeded, outcome)
        assertEquals("only the outstanding asset is requested", 1, server.requestCount)
        assertEquals("/rootfs", server.takeRequest().path)
    }

    @Test
    fun anAbsentJournalFinishesIdleWithoutTouchingTheNetwork() {
        val outcome = runner.run()

        assertEquals(BatchIdle, outcome)
        assertEquals(BatchIdle, lifecycle.finished)
        assertEquals(0, server.requestCount)
        assertFalse(lifecycle.events.contains("started"))
    }

    @Test
    fun anEmptyBatchSucceedsImmediately() {
        journal.write(AssetDownloadPlanner.plan(1, 1, emptyList(), downloadDirectory))

        val outcome = runner.run()

        assertEquals(BatchSucceeded, outcome)
        assertEquals(0, server.requestCount)
        assertEquals("finished", lifecycle.events.last())
    }

    @Test
    fun theSelectionContextSurvivesTheWholeBatch() {
        writePlan()
        server.enqueue(MockResponse().setBody(assetsBody))
        server.enqueue(MockResponse().setBody(rootfsBody))

        runner.run()

        // This is what lets a recreated process reattach to the chosen session.
        val reloaded = DownloadJournal(File(downloadDirectory, "journal.json")).read()!!
        assertEquals(11L, reloaded.sessionId)
        assertEquals(5L, reloaded.filesystemId)
        assertEquals(DownloadBatchState.COMPLETE, reloaded.state)
    }

    @Test
    fun aTransientFailureIsRetriedWithinTheSameBatch() {
        writePlan()
        server.enqueue(MockResponse().setResponseCode(503))
        server.enqueue(MockResponse().setBody(assetsBody))
        server.enqueue(MockResponse().setBody(rootfsBody))

        val outcome = runner.run()

        assertEquals(BatchSucceeded, outcome)
        assertEquals(3, server.requestCount)
    }
}
