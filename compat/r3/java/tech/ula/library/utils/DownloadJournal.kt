package tech.ula.library.utils

import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import okio.Buffer
import okio.buffer
import okio.source
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

enum class DownloadItemState { PENDING, IN_PROGRESS, COMPLETE, FAILED }

enum class DownloadBatchState { PENDING, RUNNING, COMPLETE, FAILED }

/**
 * One asset the runtime must have on disk before setup can continue. [bytesWritten]
 * mirrors the length of the item's part file so an interrupted transfer can resume
 * from the byte the journal last recorded.
 */
data class DownloadItem(
    val id: String,
    val url: String,
    val destination: String,
    val expectedBytes: Long = UNKNOWN_LENGTH,
    val sha256: String = "",
    val bytesWritten: Long = 0,
    val attempts: Int = 0,
    val state: DownloadItemState = DownloadItemState.PENDING,
    val error: String? = null
) {
    val partFile: File get() = File("$destination.part")

    val destinationFile: File get() = File(destination)

    /** Custom filesystem sources are network-derived and carry no locked digest. */
    val isLocked: Boolean get() = sha256.isNotBlank()

    companion object {
        const val UNKNOWN_LENGTH = -1L
    }
}

/**
 * The downloads one session needs, carrying the selection context so a process that
 * is recreated mid-download can reattach to the session the user actually chose
 * rather than dropping them back at selection.
 */
data class DownloadBatch(
    val sessionId: Long,
    val filesystemId: Long,
    val items: List<DownloadItem>,
    val state: DownloadBatchState = DownloadBatchState.PENDING
) {
    val completedCount: Int get() = items.count { it.state == DownloadItemState.COMPLETE }

    val totalCount: Int get() = items.size

    fun withItem(updated: DownloadItem): DownloadBatch {
        return copy(items = items.map { if (it.id == updated.id) updated else it })
    }
}

/**
 * Durable batch state, written beside the part files it describes.
 *
 * The journal lives in the same directory as the transfers it tracks and is
 * published by the same write-temp-then-rename discipline, so a process killed at
 * any point leaves the recorded offsets and the bytes on disk consistent with each
 * other. A reader that finds a truncated or unreadable journal treats it as absent
 * and setup restarts cleanly rather than resuming from a bad offset.
 */
class DownloadJournal(private val journalFile: File) {

    fun read(): DownloadBatch? {
        if (!journalFile.exists() || journalFile.length() == 0L) return null
        return try {
            journalFile.source().buffer().use { source ->
                JsonReader.of(source).use { reader -> readBatch(reader) }
            }
        } catch (err: IOException) {
            null
        } catch (err: IllegalStateException) {
            // A partially written journal is not evidence of anything.
            null
        }
    }

    fun write(batch: DownloadBatch) {
        journalFile.parentFile?.mkdirs()
        val temporary = File(journalFile.absolutePath + ".tmp")

        // Rendered up front: closing the writer closes whatever sink it wraps, and
        // the file descriptor has to still be open to be synced.
        val encoded = Buffer()
        JsonWriter.of(encoded).use { writer -> writeBatch(writer, batch) }
        val bytes = encoded.readByteArray()

        FileOutputStream(temporary).use { stream ->
            stream.write(bytes)
            stream.flush()
            stream.fd.sync()
        }
        if (!temporary.renameTo(journalFile)) {
            journalFile.delete()
            if (!temporary.renameTo(journalFile)) {
                temporary.delete()
                throw IOException("Could not publish the download journal.")
            }
        }
    }

    fun clear() {
        journalFile.delete()
        File(journalFile.absolutePath + ".tmp").delete()
    }

    private fun writeBatch(writer: JsonWriter, batch: DownloadBatch) {
        writer.beginObject()
        writer.name("schema_version").value(SCHEMA_VERSION.toLong())
        writer.name("session_id").value(batch.sessionId)
        writer.name("filesystem_id").value(batch.filesystemId)
        writer.name("state").value(batch.state.name)
        writer.name("items")
        writer.beginArray()
        batch.items.forEach { item ->
            writer.beginObject()
            writer.name("id").value(item.id)
            writer.name("url").value(item.url)
            writer.name("destination").value(item.destination)
            writer.name("expected_bytes").value(item.expectedBytes)
            writer.name("sha256").value(item.sha256)
            writer.name("bytes_written").value(item.bytesWritten)
            writer.name("attempts").value(item.attempts.toLong())
            writer.name("state").value(item.state.name)
            writer.name("error").value(item.error)
            writer.endObject()
        }
        writer.endArray()
        writer.endObject()
    }

    private fun readBatch(reader: JsonReader): DownloadBatch? {
        var sessionId: Long? = null
        var filesystemId: Long? = null
        var state = DownloadBatchState.PENDING
        var items: List<DownloadItem>? = null

        reader.beginObject()
        while (reader.hasNext()) {
            when (reader.nextName()) {
                "session_id" -> sessionId = reader.nextLong()
                "filesystem_id" -> filesystemId = reader.nextLong()
                "state" -> state = readEnum(reader.nextString(), DownloadBatchState.PENDING)
                "items" -> items = readItems(reader)
                else -> reader.skipValue()
            }
        }
        reader.endObject()

        if (sessionId == null || filesystemId == null || items == null) return null
        return DownloadBatch(sessionId, filesystemId, items, state)
    }

    private fun readItems(reader: JsonReader): List<DownloadItem> {
        val items = mutableListOf<DownloadItem>()
        reader.beginArray()
        while (reader.hasNext()) {
            var id = ""
            var url = ""
            var destination = ""
            var expectedBytes = DownloadItem.UNKNOWN_LENGTH
            var sha256 = ""
            var bytesWritten = 0L
            var attempts = 0
            var itemState = DownloadItemState.PENDING
            var error: String? = null

            reader.beginObject()
            while (reader.hasNext()) {
                when (reader.nextName()) {
                    "id" -> id = reader.nextString()
                    "url" -> url = reader.nextString()
                    "destination" -> destination = reader.nextString()
                    "expected_bytes" -> expectedBytes = reader.nextLong()
                    "sha256" -> sha256 = reader.nextString()
                    "bytes_written" -> bytesWritten = reader.nextLong()
                    "attempts" -> attempts = reader.nextInt()
                    "state" -> itemState = readEnum(reader.nextString(), DownloadItemState.PENDING)
                    "error" -> error =
                        if (reader.peek() == JsonReader.Token.NULL) {
                            reader.nextNull<String>()
                        } else {
                            reader.nextString()
                        }
                    else -> reader.skipValue()
                }
            }
            reader.endObject()

            if (id.isNotBlank() && url.isNotBlank() && destination.isNotBlank()) {
                items.add(
                    DownloadItem(
                        id, url, destination, expectedBytes, sha256,
                        bytesWritten, attempts, itemState, error
                    )
                )
            }
        }
        reader.endArray()
        return items
    }

    private inline fun <reified T : Enum<T>> readEnum(name: String, fallback: T): T {
        return enumValues<T>().firstOrNull { it.name == name } ?: fallback
    }

    companion object {
        const val SCHEMA_VERSION = 1
    }
}
