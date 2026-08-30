package tech.ula.library.utils

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * The r3 release run failed on seventeen of twenty emulator jobs with the same
 * shape, recorded in every evidence journal:
 *
 *   "expected_bytes": 307175937, "bytes_written": 8261175,
 *   "attempts": 5, "state": "FAILED", "error": "The download was interrupted."
 *
 * A ten second network outage consumed the whole attempt budget in under a
 * second, because retries were issued back to back with no wait. The bytes
 * already on disk were fine and resume would have worked, but no attempt was
 * left by the time the network returned.
 */
class R3TransferOutageTest {

    @get:Rule val tempFolder = TemporaryFolder()

    private lateinit var server: MockWebServer
    private lateinit var destination: File
    private val waits = mutableListOf<Long>()

    private val payload = "userland rootfs payload"

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        destination = File(tempFolder.newFolder("downloads"), "rootfs.tar.gz")
        waits.clear()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun transfer() = ResumableAssetTransfer(
        client = OkHttpClient.Builder()
            .connectTimeout(2, TimeUnit.SECONDS)
            .readTimeout(2, TimeUnit.SECONDS)
            .build(),
        // Record instead of sleeping, so the test asserts the policy rather
        // than spending the wall time it describes.
        sleeper = { millis -> waits.add(millis) }
    )

    private fun item() = DownloadItem(
        id = "rootfs",
        url = server.url("/rootfs.tar.gz").toString(),
        destination = destination.absolutePath,
        expectedBytes = payload.toByteArray().size.toLong(),
        sha256 = MessageDigest.getInstance("SHA-256")
            .digest(payload.toByteArray())
            .joinToString("") { "%02x".format(it) }
    )

    @Test
    fun transientOutageDoesNotConsumeTheWholeAttemptBudget() {
        // Four failures standing in for the outage, then the network returns.
        repeat(4) { server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START)) }
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        val result = transfer().transfer(item())

        assertTrue("the transfer must survive a transient outage", result is TransferSucceeded)
        assertEquals(payload, destination.readText())
    }

    @Test
    fun retriesWaitAndTheWaitGrows() {
        repeat(4) { server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START)) }
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        transfer().transfer(item())

        assertEquals("every retry must wait", 4, waits.size)
        assertTrue("the wait must grow, not repeat", waits.zipWithNext().all { it.second > it.first })
        assertTrue(
            "five attempts must outlast a ten second outage",
            waits.sum() >= 10_000
        )
    }

    @Test
    fun progressResetsTheBudgetSoALongDownloadCanOutlastManyInterruptions() {
        // A 307MB asset over a flaky link is interrupted far more often than
        // the budget allows, but each interruption leaves more bytes on disk.
        repeat(3) {
            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .setBody(payload.substring(0, 4))
                    .setSocketPolicy(SocketPolicy.DISCONNECT_AT_END)
            )
        }
        repeat(6) { server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START)) }

        val result = transfer().transfer(item())

        assertTrue(
            "an attempt that wrote bytes must not count toward exhaustion",
            server.requestCount > 5
        )
        assertTrue(result is TransferFailed)
    }
}
