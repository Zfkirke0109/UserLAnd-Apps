package tech.ula.library.utils

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import tech.ula.customlibrary.BuildConfig
import tech.ula.library.model.entities.Asset
import tech.ula.library.model.entities.Filesystem
import java.io.File
import java.io.IOException

class FilesystemManager(
    private val ulaFiles: UlaFiles,
    private val busyboxExecutor: BusyboxExecutor,
    private val logger: Logger = SentryLogger()
) {

    private val filesDirPath = ulaFiles.filesDir.path
    private val filesystemExtractionSuccess = ".success_filesystem_extraction"
    private val filesystemExtractionFailure = ".failure_filesystem_extraction"
    private val rootfsArchiveName = "rootfs.tar.gz"

    // Support assets v1.5.1 no longer extract the root filesystem, so extraction is
    // owned here and only anchors this class has verified may be treated as success.
    private val requiredFilesystemAnchors = listOf("bin/sh", "etc/passwd")

    // execInProot.sh binds each of these out of the filesystem's own support directory.
    private val requiredSupportAnchors =
        listOf("nosudo", "userland_profile.sh", "ld.so.preload")

    private fun getSupportDirectoryPath(targetDirectoryName: String): String {
        return "$filesDirPath/$targetDirectoryName/support"
    }

    @Throws(Exception::class)
    fun copyAssetsToFilesystem(filesystem: Filesystem) {
        val distributionType = filesystem.distributionType
        val targetFilesystemName = "${filesystem.id}"
        val sharedDirectory = File("$filesDirPath/$distributionType")
        val targetDirectory = File("$filesDirPath/$targetFilesystemName/support")
        if (!targetDirectory.exists()) targetDirectory.mkdirs()
        val files = sharedDirectory.listFiles()
        files?.let {
            for (file in files) {
                if (file.name.contains("rootfs") && filesystem.isCreatedFromBackup) continue
                val targetFile = File("${targetDirectory.absolutePath}/${file.name}")
                file.copyTo(targetFile, overwrite = true)
                ulaFiles.makePermissionsUsable(targetDirectory.absolutePath, file.name)
            }
        }
    }

    /**
     * Finds the payload to unpack, in the support directory first and the
     * distribution directory second.
     *
     * copyAssetsToFilesystem is what normally brings the payload across, and the
     * state machine calls it only when a distribution asset is missing or out of
     * date. rootfs.tar.gz is not one of those assets, so once the ones that are
     * have been copied and the version recorded, a later attempt skips the copy
     * and finds nothing here — reported as a missing download while the payload
     * sits in the distribution directory where staging left it. Reading from
     * there costs nothing and makes a retry work the way the first attempt did.
     */
    private fun resolveRootfsArchive(filesystem: Filesystem, supportDirectory: File): File {
        val staged = File(supportDirectory, rootfsArchiveName)
        if (staged.exists() && staged.length() > 0L) return staged

        val downloaded = File(
            "$filesDirPath/${filesystem.distributionType}",
            rootfsArchiveName
        )
        return if (downloaded.exists() && downloaded.length() > 0L) downloaded else staged
    }

    fun removeRootfsFilesFromFilesystem(targetFilesystemName: String) {
        val supportDirectory = File(getSupportDirectoryPath(targetFilesystemName))
        supportDirectory.walkBottomUp().forEach {
            if (it.name.contains("rootfs.tar.gz")) it.delete()
        }
    }

    /**
     * Reads the downloaded archive with static BusyBox before anything is written to
     * disk. An archive that cannot be listed, is empty, or names a member outside the
     * filesystem directory is rejected while it is still inert.
     */
    fun validateRootfsArchive(archive: File): ExecutionResult {
        if (!archive.exists() || archive.length() == 0L) {
            return FailedExecution("The $rootfsArchiveName download is missing or empty.")
        }

        val members = mutableListOf<String>()
        val listing = busyboxExecutor.runHostApplet(
            "tar",
            listOf("-tzf", archive.absolutePath)
        ) { line -> members.add(line.trim()) }

        if (listing !is SuccessfulExecution) {
            // Saying only that the archive could not be read throws away the one
            // fact needed to tell a truncated download from a BusyBox that will
            // not run. Carry the underlying reason and the size we actually have.
            val cause = when (listing) {
                is FailedExecution -> listing.reason
                is MissingExecutionAsset -> "missing ${listing.asset}"
                else -> "no reason reported"
            }
            return FailedExecution(
                "The $rootfsArchiveName download could not be read " +
                    "(${archive.length()} bytes on disk, $cause)."
            )
        }
        if (members.isEmpty()) {
            return FailedExecution("The $rootfsArchiveName download contains no files.")
        }
        if (members.any { it.isUnsafeArchiveMember() }) {
            // The offending name is untrusted input and is deliberately not echoed.
            return FailedExecution(
                "The $rootfsArchiveName download contains an unsafe path."
            )
        }
        return SuccessfulExecution
    }

    /**
     * Extracts the root filesystem, creates the non-root user, and only then records
     * success. Existing filesystem content is never deleted, so this doubles as the
     * repair path for an r2 installation whose success marker was written without a
     * usable filesystem. The archive is retained whenever a stage fails so that Retry
     * does not have to download it again.
     */
    suspend fun extractFilesystem(
        filesystem: Filesystem,
        listener: (String) -> Any
    ): ExecutionResult = withContext(Dispatchers.IO) {
        val filesystemDirName = "${filesystem.id}"
        val filesystemRoot = File("$filesDirPath/$filesystemDirName")
        val supportDirectory = File(getSupportDirectoryPath(filesystemDirName))
        val successMarker = File(supportDirectory, filesystemExtractionSuccess)
        val failureMarker = File(supportDirectory, filesystemExtractionFailure)
        filesystemRoot.mkdirs()
        supportDirectory.mkdirs()
        // A repair must never inherit the verdict of an earlier attempt.
        successMarker.delete()
        failureMarker.delete()

        val archive = resolveRootfsArchive(filesystem, supportDirectory)

        val validation = validateRootfsArchive(archive)
        if (validation !is SuccessfulExecution) {
            return@withContext recordFailure(failureMarker, validation)
        }

        val extraction = busyboxExecutor.runHostApplet(
            "tar",
            extractionArguments(archive, filesystemRoot),
            listener
        )
        if (extraction !is SuccessfulExecution) {
            return@withContext recordFailure(failureMarker, extraction)
        }

        val userCreation = busyboxExecutor.executeProotCommand(
            "/support/common/addNonRootUser.sh",
            filesystemDirName,
            commandShouldTerminate = true,
            env = userCreationEnvironment(filesystem),
            listener = listener
        )
        if (userCreation !is SuccessfulExecution) {
            return@withContext recordFailure(failureMarker, userCreation)
        }

        val missingAnchor =
            missingFilesystemAnchor(filesystemDirName, filesystem.defaultUsername)
                ?: missingSupportAnchor(filesystemDirName)
        if (missingAnchor != null) {
            return@withContext recordFailure(
                failureMarker,
                FailedExecution("Extraction did not produce $missingAnchor.")
            )
        }

        archive.delete()
        successMarker.createNewFile()
        return@withContext SuccessfulExecution
    }

    suspend fun compressFilesystem(
        filesystem: Filesystem,
        scopedExternalDestination: File,
        listener: (String) -> Any
    ) = withContext(Dispatchers.IO) {
        val filesystemDirName = "${filesystem.id}"
        val command = "/support/common/compressFilesystem.sh"
        val env = HashMap<String, String>()
        env["TAR_PATH"] = scopedExternalDestination.absolutePath
        env["EXCLUDE_SUPPORT"] = supportExclusionArgument()

        return@withContext busyboxExecutor.executeProotCommand(
                command,
                filesystemDirName,
                commandShouldTerminate = true,
                env = env,
                listener = listener
        )
    }

    fun isExtractionComplete(targetDirectoryName: String): Boolean {
        val supportPath = getSupportDirectoryPath(targetDirectoryName)
        val success = File("$supportPath/$filesystemExtractionSuccess")
        val failure = File("$supportPath/$filesystemExtractionFailure")
        return success.exists() || failure.exists()
    }

    /**
     * A success marker is evidence of a completed extraction only when the root
     * filesystem it describes is still intact. An r2 marker written over an
     * unextracted filesystem reports false here, which sends session startup back
     * through extraction instead of into a session that cannot start.
     */
    fun hasUsableFilesystem(targetDirectoryName: String, username: String? = null): Boolean {
        val supportPath = getSupportDirectoryPath(targetDirectoryName)
        if (!File("$supportPath/$filesystemExtractionSuccess").exists()) return false
        return missingFilesystemAnchor(targetDirectoryName, username) == null
    }

    fun hasFilesystemBeenSuccessfullyExtracted(targetDirectoryName: String): Boolean {
        return hasUsableFilesystem(targetDirectoryName)
    }

    /**
     * Sends a filesystem back through extraction, and touches nothing else.
     *
     * Repair removes only the two extraction markers. It deletes no filesystem
     * content, no user home, and no downloaded payload, because extraction already
     * unpacks over the existing tree and preserves what it finds there. A repair
     * that reached further would be able to destroy exactly the data the user came
     * back to recover.
     */
    fun invalidateExtraction(targetDirectoryName: String): Boolean {
        val supportPath = getSupportDirectoryPath(targetDirectoryName)
        val success = File("$supportPath/$filesystemExtractionSuccess")
        val failure = File("$supportPath/$filesystemExtractionFailure")
        val removed = success.exists() || failure.exists()
        success.delete()
        failure.delete()
        return removed
    }

    fun areAllRequiredAssetsPresent(
        targetDirectoryName: String,
        distributionAssetList: List<Asset>
    ): Boolean {
        val supportDirectory = File(getSupportDirectoryPath(targetDirectoryName))
        if (!supportDirectory.exists() || !supportDirectory.isDirectory) return false

        val supportFiles = supportDirectory.listFiles() ?: return false
        val supportDirectoryFileNames = supportFiles.map { it.name }
        return distributionAssetList.all {
            supportDirectoryFileNames.contains(it.name)
        }
    }

    @Throws(IOException::class)
    suspend fun deleteFilesystem(filesystemId: Long) = withContext(Dispatchers.IO) {
        val filesystemDirectory = File("$filesDirPath/$filesystemId")
        if (!filesystemDirectory.exists() || !filesystemDirectory.isDirectory) return@withContext
        // CWD for this script is the files dir, running without proot
        val command = "support/deleteFilesystem.sh ${filesystemDirectory.path}"
        val result = busyboxExecutor.executeScript(command)
        if (result is FailedExecution) {
            val err = IOException()
            logger.addExceptionBreadcrumb(err)
            throw err
        }
    }

    @Throws(IOException::class)
    fun moveAppScriptToRequiredLocation(appName: String, appFilesystem: Filesystem) {
        // Profile.d scripts execute in alphabetical order.
        val fileNameToForceAppScriptToExecuteLast = "zzzzzzzzzzzzzzzz.sh"
        val appScriptSource = File("$filesDirPath/apps/$appName/$appName.sh")
        val appFilesystemProfileDDir = File("$filesDirPath/${appFilesystem.id}/etc/profile.d")
        val appScriptProfileDTarget = File("$appFilesystemProfileDDir/$fileNameToForceAppScriptToExecuteLast")

        try {
            appFilesystemProfileDDir.mkdirs()
            appScriptSource.copyTo(appScriptProfileDTarget, overwrite = true)
        } catch (err: Exception) {
            val exception = IOException()
            logger.addExceptionBreadcrumb(exception)
            throw exception
        }
    }

    /**
     * Returns the first root-filesystem anchor that is missing, or null when the
     * filesystem is intact. A username is supplied once its home directory is
     * expected to exist.
     */
    private fun missingFilesystemAnchor(
        targetDirectoryName: String,
        username: String?
    ): String? {
        val filesystemRoot = File("$filesDirPath/$targetDirectoryName")

        requiredFilesystemAnchors.firstOrNull { !File(filesystemRoot, it).exists() }
            ?.let { return "/$it" }
        if (username != null && !File(filesystemRoot, "home/$username").isDirectory) {
            return "/home/$username"
        }
        return null
    }

    /**
     * Returns the first proot binding source the filesystem's support directory is
     * missing. This is checked when extraction completes rather than on every startup
     * predicate, because copyAssetsToFilesystem restores these files on its own and a
     * missing one must not cost the user another root-filesystem download.
     */
    private fun missingSupportAnchor(targetDirectoryName: String): String? {
        val supportDirectory = File(getSupportDirectoryPath(targetDirectoryName))
        return requiredSupportAnchors.firstOrNull {
            !File(supportDirectory, it).exists()
        }?.let { "support/$it" }
    }

    private fun recordFailure(failureMarker: File, result: ExecutionResult): ExecutionResult {
        failureMarker.createNewFile()
        return when (result) {
            is FailedExecution -> result
            is MissingExecutionAsset -> FailedExecution("Missing ${result.asset}.")
            else -> FailedExecution("Extraction did not complete.")
        }
    }

    /**
     * Reproduces the exclusions the v1.3.4 support script applied inside proot. The
     * archive is unpacked over the existing filesystem so that a repair preserves
     * unrelated user-home content and the downloaded support directory.
     */
    private fun extractionArguments(archive: File, filesystemRoot: File): List<String> {
        val supportExclusion =
            if (BuildConfig.FILESYSTEM_ONLY_ASSET) "support/common" else "support"
        val exclusions = listOf(
            "sys", "dev", "proc", "data", "mnt", "host-rootfs", supportExclusion,
            "sdcard", "etc/mtab", "usr/local/bin/sudo",
            "etc/profile.d/userland_profile.sh", "etc/ld.so.preload"
        )
        // Members are stored either bare or "./"-prefixed depending on how the
        // archive was rolled, and an exclusion only matches the stored name.
        return listOf(
            "-xzvf", archive.absolutePath,
            "-C", filesystemRoot.absolutePath
        ) + exclusions.flatMap { listOf("--exclude", it, "--exclude", "./$it") }
    }

    private fun userCreationEnvironment(filesystem: Filesystem): HashMap<String, String> {
        val env = HashMap<String, String>()
        env["INITIAL_USERNAME"] = filesystem.defaultUsername
        env["INITIAL_PASSWORD"] = filesystem.defaultPassword
        env["INITIAL_VNC_PASSWORD"] = filesystem.defaultVncPassword
        env["EXCLUDE_SUPPORT"] = supportExclusionArgument()
        return env
    }

    private fun supportExclusionArgument(): String {
        return if (BuildConfig.FILESYSTEM_ONLY_ASSET) "--exclude support/common"
        else "--exclude support"
    }

    private fun String.isUnsafeArchiveMember(): Boolean {
        return isBlank() || startsWith("/") || split('/').any { it == ".." }
    }
}
