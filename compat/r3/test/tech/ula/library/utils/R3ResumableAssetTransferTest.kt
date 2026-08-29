package tech.ula.library.utils

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class R3ResumableAssetTransferTest {

    @get:Rule val tempFolder = TemporaryFolder()

    private lateinit var server: MockWebServer
    private lateinit var destination: File
    private lateinit var part: File
    private lateinit var transfer: ResumableAssetTransfer

    private val payload = "userland rootfs payload"

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        destination = File(tempFolder.newFolder("downloads"), "rootfs.tar.gz")
        part = File("${destination.absolutePath}.part")
        transfer = ResumableAssetTransfer(
            OkHttpClient.Builder()
                .connectTimeout(2, TimeUnit.SECONDS)
                .readTimeout(2, TimeUnit.SECONDS)
                .build()
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun item(
        sha256: String = sha256Of(payload),
        expectedBytes: Long = payload.toByteArray().size.toLong()
    ) = DownloadItem(
        id = "rootfs",
        url = server.url("/rootfs.tar.gz").toString(),
        destination = destination.absolutePath,
        expectedBytes = expectedBytes,
        sha256 = sha256
    )

    private fun sha256Of(text: String): String {
        return MessageDigest.getInstance("SHA-256")
            .digest(text.toByteArray())
            .joinToString("") { "%02x".format(it) }
    }

    @Test
    fun resumesPartFileWithRangeAndPublishesAtomically() {
        val alreadyOnDisk = payload.substring(0, 4)
        part.parentFile.mkdirs()
        part.writeText(alreadyOnDisk)
        server.enqueue(
            MockResponse()
                .setResponseCode(206)
                .setHeader("Content-Range", "bytes 4-${payload.length - 1}/${payload.length}")
                .setBody(payload.substring(4))
        )

        val result = transfer.transfer(item())

        assertTrue(result is TransferSucceeded)
        assertEquals("bytes=4-", server.takeRequest().getHeader("Range"))
        assertEquals(payload, destination.readText())
        assertFalse("the part file must not survive publication", part.exists())
    }

    @Test
    fun serverIgnoringRangeRestartsWithoutDuplicatingBytes() {
        part.parentFile.mkdirs()
        part.writeText(payload.substring(0, 4))
        // A server that answers 200 is resending the whole body, not continuing.
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        val result = transfer.transfer(item())

        assertTrue(result is TransferSucceeded)
        assertEquals("bytes=4-", server.takeRequest().getHeader("Range"))
        assertEquals(payload, destination.readText())
        assertEquals(payload.toByteArray().size.toLong(), destination.length())
    }

    @Test
    fun freshDownloadSendsNoRangeHeader() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        val result = transfer.transfer(item())

        assertTrue(result is TransferSucceeded)
        assertNull(server.takeRequest().getHeader("Range"))
        assertEquals(payload, destination.readText())
    }

    @Test
    fun checksumMismatchDeletesPublishAndReturnsTerminalFailure() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        val result = transfer.transfer(
            item(sha256 = "0000000000000000000000000000000000000000000000000000000000000000")
        )

        assertTrue(result is TransferFailed)
        assertTrue((result as TransferFailed).terminal)
        assertFalse("a mismatched asset must never be published", destination.exists())
        assertFalse(part.exists())
        assertEquals(1, server.requestCount)
    }

    @Test
    fun retriesStopAfterFiveAttempts() {
        repeat(6) { server.enqueue(MockResponse().setResponseCode(503)) }

        val result = transfer.transfer(item())

        assertTrue(result is TransferFailed)
        assertTrue((result as TransferFailed).terminal)
        assertEquals(5, server.requestCount)
        assertFalse(destination.exists())
    }

    @Test
    fun transientFailureIsRetriedAndThenSucceeds() {
        server.enqueue(MockResponse().setResponseCode(503))
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        val result = transfer.transfer(item())

        assertTrue(result is TransferSucceeded)
        assertEquals(2, server.requestCount)
        assertEquals(payload, destination.readText())
    }

    @Test
    fun clientErrorIsTerminalWithoutRetrying() {
        repeat(5) { server.enqueue(MockResponse().setResponseCode(404)) }

        val result = transfer.transfer(item())

        assertTrue(result is TransferFailed)
        assertTrue((result as TransferFailed).terminal)
        assertEquals("a 404 will not resolve by asking again", 1, server.requestCount)
    }

    @Test
    fun shortBodyIsRetriedRatherThanPublished() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload.substring(0, 5)))
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        val result = transfer.transfer(item())

        assertTrue(result is TransferSucceeded)
        assertEquals(2, server.requestCount)
        assertEquals(payload, destination.readText())
    }

    @Test
    fun truncatedBodyResumesFromTheRecordedOffset() {
        // The connection drops partway through, then the retry resumes.
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(Buffer().writeUtf8(payload.substring(0, 4)))
                .setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_END)
        )
        server.enqueue(
            MockResponse()
                .setResponseCode(206)
                .setHeader("Content-Range", "bytes 4-${payload.length - 1}/${payload.length}")
                .setBody(payload.substring(4))
        )

        val result = transfer.transfer(item())

        assertTrue(result is TransferSucceeded)
        assertEquals(payload, destination.readText())
        assertNull(server.takeRequest().getHeader("Range"))
        assertEquals("bytes=4-", server.takeRequest().getHeader("Range"))
    }

    @Test
    fun unlockedItemPublishesWithoutADigest() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        // Custom filesystem sources are network-derived and carry no locked digest.
        val result = transfer.transfer(item(sha256 = ""))

        assertTrue(result is TransferSucceeded)
        assertEquals(payload, destination.readText())
    }

    @Test
    fun progressReportsMonotonicBytes() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))
        val observed = mutableListOf<Long>()

        transfer.transfer(item()) { written, _ -> observed.add(written) }

        assertTrue(observed.isNotEmpty())
        assertEquals(observed.sorted(), observed)
        assertEquals(payload.toByteArray().size.toLong(), observed.last())
    }

    @Test
    fun successfulTransferReportsCompleteState() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(payload))

        val result = transfer.transfer(item()) as TransferSucceeded

        assertEquals(DownloadItemState.COMPLETE, result.item.state)
        assertEquals(payload.toByteArray().size.toLong(), result.item.bytesWritten)
        assertNull(result.item.error)
    }
}
