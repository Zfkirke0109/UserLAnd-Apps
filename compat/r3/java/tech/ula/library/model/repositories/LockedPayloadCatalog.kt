package tech.ula.library.model.repositories

import com.squareup.moshi.JsonReader
import okio.BufferedSource
import okio.Buffer

/** One first-run payload, selected by exact release data rather than `latest`. */
data class LockedPayload(
    val filename: String,
    val release: String,
    val url: String,
    val size: Long,
    val sha256: String
)

data class LockedAbi(
    val assetList: List<String>,
    val payloads: Map<String, LockedPayload>
)

data class LockedApp(
    val id: String,
    val packageId: String,
    val repository: String,
    val abis: Map<String, LockedAbi>
)

/**
 * The immutable payload catalog bundled into each APK.
 *
 * Default setup resolves every download through this catalog, so a first run
 * fetches the exact bytes the release was built against instead of whatever a
 * remote `latest` pointer happens to name at the time. Lookups are keyed by the
 * package name and the translated architecture, which is what an installed APK
 * actually knows about itself.
 */
class LockedPayloadCatalog(val apps: List<LockedApp>) {

    private val byPackage = apps.associateBy { it.packageId }

    fun app(packageName: String): LockedApp? = byPackage[packageName]

    fun abi(packageName: String, archType: String): LockedAbi? =
        byPackage[packageName]?.abis?.get(archType)

    fun payload(packageName: String, archType: String, filename: String): LockedPayload? =
        abi(packageName, archType)?.payloads?.get(filename)

    fun assetList(packageName: String, archType: String): List<String> =
        abi(packageName, archType)?.assetList.orEmpty()

    /** True when this build's package and architecture are both covered. */
    fun supports(packageName: String, archType: String): Boolean =
        abi(packageName, archType) != null

    companion object {
        const val ASSETS_PAYLOAD = "assets.tar.gz"
        const val ROOTFS_PAYLOAD = "rootfs.tar.gz"

        fun from(text: String): LockedPayloadCatalog =
            parse(Buffer().writeUtf8(text))

        fun parse(source: BufferedSource): LockedPayloadCatalog {
            JsonReader.of(source).use { reader ->
                var apps: List<LockedApp> = emptyList()
                reader.beginObject()
                while (reader.hasNext()) {
                    when (reader.nextName()) {
                        "apps" -> apps = readApps(reader)
                        else -> reader.skipValue()
                    }
                }
                reader.endObject()
                return LockedPayloadCatalog(apps)
            }
        }

        private fun readApps(reader: JsonReader): List<LockedApp> {
            val apps = mutableListOf<LockedApp>()
            reader.beginArray()
            while (reader.hasNext()) {
                var id = ""
                var packageId = ""
                var repository = ""
                var abis: Map<String, LockedAbi> = emptyMap()

                reader.beginObject()
                while (reader.hasNext()) {
                    when (reader.nextName()) {
                        "id" -> id = reader.nextString()
                        "package_id" -> packageId = reader.nextString()
                        "repository" -> repository = reader.nextString()
                        "abis" -> abis = readAbis(reader)
                        else -> reader.skipValue()
                    }
                }
                reader.endObject()

                if (packageId.isNotBlank()) {
                    apps.add(LockedApp(id, packageId, repository, abis))
                }
            }
            reader.endArray()
            return apps
        }

        private fun readAbis(reader: JsonReader): Map<String, LockedAbi> {
            val abis = mutableMapOf<String, LockedAbi>()
            reader.beginObject()
            while (reader.hasNext()) {
                val abi = reader.nextName()
                var assetList: List<String> = emptyList()
                val payloads = mutableMapOf<String, LockedPayload>()

                reader.beginObject()
                while (reader.hasNext()) {
                    when (val key = reader.nextName()) {
                        "asset_list" -> assetList = readStrings(reader)
                        else -> {
                            val payload = readPayload(reader)
                            if (payload != null) payloads[key] = payload
                        }
                    }
                }
                reader.endObject()
                abis[abi] = LockedAbi(assetList, payloads)
            }
            reader.endObject()
            return abis
        }

        private fun readStrings(reader: JsonReader): List<String> {
            val values = mutableListOf<String>()
            reader.beginArray()
            while (reader.hasNext()) values.add(reader.nextString())
            reader.endArray()
            return values
        }

        private fun readPayload(reader: JsonReader): LockedPayload? {
            if (reader.peek() != JsonReader.Token.BEGIN_OBJECT) {
                reader.skipValue()
                return null
            }
            var filename = ""
            var release = ""
            var url = ""
            var size = 0L
            var sha256 = ""

            reader.beginObject()
            while (reader.hasNext()) {
                when (reader.nextName()) {
                    "filename" -> filename = reader.nextString()
                    "release" -> release = reader.nextString()
                    "url" -> url = reader.nextString()
                    "size" -> size = reader.nextLong()
                    "sha256" -> sha256 = reader.nextString()
                    else -> reader.skipValue()
                }
            }
            reader.endObject()

            // A payload without a URL or a digest cannot be selected by exact bytes,
            // which is the only reason this catalog exists.
            if (url.isBlank() || sha256.isBlank()) return null
            return LockedPayload(filename, release, url, size, sha256)
        }
    }
}
