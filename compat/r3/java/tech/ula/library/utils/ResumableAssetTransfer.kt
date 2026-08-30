package tech.ula.library.utils

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

sealed class TransferResult
data class TransferSucceeded(val item: DownloadItem) : TransferResult()
data class TransferFailed(
    val item: DownloadItem,
    val reason: String,
    val terminal: Boolean
) : TransferResult()

/**
 * Moves one asset from its locked URL onto disk, surviving interruption.
 *
 * Bytes land in a sibling part file and are published to the real destination by a
 * rename only after the transfer has been verified, so a reader never observes a
 * partial or unverified asset. A part file that already holds bytes is resumed with
 * a Range request; a server that answers 200 instead of 206 is honored by
 * restarting the file rather than appending onto the bytes it just re-sent.
 */
class ResumableAssetTransfer(
    private val client: OkHttpClient = defaultClient(),
    private val maxAttempts: Int = DEFAULT_MAX_ATTEMPTS,
    private val backoffMillis: (Int) -> Long = ::defaultBackoffMillis,
    private val sleeper: (Long) -> Unit = { millis -> Thread.sleep(millis) },
    private val maxTotalAttempts: Int = DEFAULT_MAX_TOTAL_ATTEMPTS
) {

    fun transfer(
        item: DownloadItem,
        onProgress: (bytesWritten: Long, expectedBytes: Long) -> Unit = { _, _ -> }
    ): TransferResult {
        val part = item.partFile
        part.parentFile?.mkdirs()

        var current = item
        var lastReason = "The download did not start."

        // The budget counts attempts that achieved nothing. An attempt that wrote
        // bytes made progress and earns a fresh budget, so a large asset over a
        // flaky link is not capped at a handful of interruptions; a hard ceiling
        // still stops a transfer that would otherwise run forever.
        var attemptsSinceProgress = 0
        var totalAttempts = 0

        while (attemptsSinceProgress < maxAttempts && totalAttempts < maxTotalAttempts) {
            if (totalAttempts > 0) sleeper(backoffMillis(attemptsSinceProgress - 1))
            totalAttempts++
            current = current.copy(attempts = totalAttempts)
            val bytesBefore = current.bytesWritten
            when (val outcome = attemptTransfer(current, onProgress)) {
                is TransferSucceeded -> return outcome
                is TransferFailed -> {
                    if (outcome.terminal) return outcome
                    lastReason = outcome.reason
                    current = outcome.item
                    attemptsSinceProgress =
                        if (current.bytesWritten > bytesBefore) 0 else attemptsSinceProgress + 1
                }
            }
        }

        return TransferFailed(
            current.copy(state = DownloadItemState.FAILED, error = lastReason),
            lastReason,
            terminal = true
        )
    }

    private fun attemptTransfer(
        item: DownloadItem,
        onProgress: (Long, Long) -> Unit
    ): TransferResult {
        val part = item.partFile
        val resumeFrom = if (part.exists()) part.length() else 0L

        val builder = Request.Builder().url(item.url)
        if (resumeFrom > 0) builder.header("Range", "bytes=$resumeFrom-")

        return try {
            client.newCall(builder.build()).execute().use { response ->
                consume(item, response, resumeFrom, onProgress)
            }
        } catch (err: IOException) {
            retryable(item, "The download was interrupted.")
        }
    }

    private fun consume(
        item: DownloadItem,
        response: Response,
        resumeFrom: Long,
        onProgress: (Long, Long) -> Unit
    ): TransferResult {
        val part = item.partFile

        if (!response.isSuccessful) {
            // 4xx other than 416 will not become successful by asking again.
            val terminal = response.code in 400..499 && response.code != HTTP_RANGE_NOT_SATISFIABLE
            val reason = "The server answered ${response.code}."
            return if (terminal) {
                part.delete()
                TransferFailed(
                    item.copy(state = DownloadItemState.FAILED, error = reason),
                    reason,
                    terminal = true
                )
            } else {
                retryable(item, reason)
            }
        }

        // Only a 206 continues the bytes already on disk. A 200 is a fresh body, so
        // appending it would duplicate whatever the part file already holds.
        val appending = response.code == HTTP_PARTIAL_CONTENT && resumeFrom > 0
        if (!appending && part.exists()) part.delete()

        val body = response.body ?: return retryable(item, "The server sent no content.")
        var written = if (appending) resumeFrom else 0L

        try {
            FileOutputStream(part, appending).use { output ->
                body.byteStream().use { input ->
                    val buffer = ByteArray(BUFFER_BYTES)
                    while (true) {
                        val read = input.read(buffer)
                        if (read == -1) break
                        output.write(buffer, 0, read)
                        written += read
                        onProgress(written, item.expectedBytes)
                    }
                }
                output.fd.sync()
            }
        } catch (err: IOException) {
            return retryable(item.copy(bytesWritten = part.length()), "The download was interrupted.")
        }

        if (item.expectedBytes != DownloadItem.UNKNOWN_LENGTH && written != item.expectedBytes) {
            // Short or overlong bodies are usually a truncated transfer, so let the
            // next attempt resume rather than failing the whole batch.
            return retryable(
                item.copy(bytesWritten = written),
                "The download ended at $written of ${item.expectedBytes} bytes."
            )
        }

        if (item.isLocked) {
            val actual = sha256Of(part)
            if (!actual.equals(item.sha256, ignoreCase = true)) {
                // The bytes are not the locked asset, so nothing here is publishable.
                part.delete()
                item.destinationFile.delete()
                val reason = "The download did not match its locked checksum."
                return TransferFailed(
                    item.copy(bytesWritten = 0, state = DownloadItemState.FAILED, error = reason),
                    reason,
                    terminal = true
                )
            }
        }

        return if (publish(part, item.destinationFile)) {
            TransferSucceeded(
                item.copy(
                    bytesWritten = written,
                    state = DownloadItemState.COMPLETE,
                    error = null
                )
            )
        } else {
            retryable(item.copy(bytesWritten = written), "The download could not be saved.")
        }
    }

    private fun retryable(item: DownloadItem, reason: String): TransferResult {
        return TransferFailed(
            item.copy(state = DownloadItemState.IN_PROGRESS, error = reason),
            reason,
            terminal = false
        )
    }

    private fun publish(part: File, destination: File): Boolean {
        if (part.renameTo(destination)) return true
        // A destination left over from an earlier run blocks the rename on some
        // filesystems; removing it is safe because the verified bytes are in part.
        destination.delete()
        return part.renameTo(destination)
    }

    private fun sha256Of(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(BUFFER_BYTES)
            while (true) {
                val read = input.read(buffer)
                if (read == -1) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    companion object {
        const val DEFAULT_MAX_ATTEMPTS = 5

        /** Ceiling across the whole transfer, however much progress is made. */
        const val DEFAULT_MAX_TOTAL_ATTEMPTS = 50
        private const val BUFFER_BYTES = 8192
        private const val HTTP_PARTIAL_CONTENT = 206
        private const val HTTP_RANGE_NOT_SATISFIABLE = 416

        fun defaultClient(): OkHttpClient {
            return OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .writeTimeout(60, TimeUnit.SECONDS)
                .callTimeout(0, TimeUnit.MILLISECONDS)
                .retryOnConnectionFailure(true)
                .build()
        }
    }
}

/**
 * How long to wait before retrying after a failure that is not terminal.
 *
 * A retry that is issued immediately is spent for nothing while the network is
 * down, so the delays grow: 1s, 2s, 4s, 8s, 16s. Five attempts then span about
 * half a minute rather than a few milliseconds.
 */
fun defaultBackoffMillis(attemptsSinceProgress: Int): Long {
    val capped = attemptsSinceProgress.coerceIn(0, 4)
    return 1000L shl capped
}
