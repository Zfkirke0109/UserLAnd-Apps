package tech.ula.library.utils

import com.nhaarman.mockitokotlin2.any
import com.nhaarman.mockitokotlin2.anyOrNull
import com.nhaarman.mockitokotlin2.argThat
import com.nhaarman.mockitokotlin2.eq
import com.nhaarman.mockitokotlin2.never
import com.nhaarman.mockitokotlin2.verify
import com.nhaarman.mockitokotlin2.whenever
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.mockito.Mock
import org.mockito.junit.MockitoJUnitRunner
import tech.ula.library.model.entities.Filesystem
import java.io.File

@RunWith(MockitoJUnitRunner::class)
class R3FilesystemManagerTest {

    @get:Rule val tempFolder = TemporaryFolder()

    @Mock lateinit var ulaFiles: UlaFiles

    @Mock lateinit var busyboxExecutor: BusyboxExecutor

    @Mock lateinit var logger: Logger

    private val username = "username"

    private val filesystem = Filesystem(
        id = 0,
        name = "apps",
        distributionType = "debian",
        archType = "arm64",
        defaultUsername = username,
        defaultPassword = "password",
        defaultVncPassword = "vncpass",
        isAppsFilesystem = true
    )

    private val filesystemId = "${filesystem.id}"
    private val successMarkerName = ".success_filesystem_extraction"
    private val failureMarkerName = ".failure_filesystem_extraction"
    private val statelessListener: (String) -> Any = { }

    private lateinit var filesystemRoot: File
    private lateinit var supportDirectory: File
    private lateinit var successMarker: File
    private lateinit var failureMarker: File
    private lateinit var archive: File
    private lateinit var userHome: File

    private lateinit var filesystemManager: FilesystemManager

    @Before
    fun setUp() {
        whenever(ulaFiles.filesDir).thenReturn(tempFolder.root)
        filesystemRoot = File(tempFolder.root, filesystemId)
        supportDirectory = File(filesystemRoot, "support").apply { mkdirs() }
        successMarker = File(supportDirectory, successMarkerName)
        failureMarker = File(supportDirectory, failureMarkerName)
        archive = File(supportDirectory, "rootfs.tar.gz")
        userHome = File(filesystemRoot, "home/$username")
        filesystemManager = FilesystemManager(ulaFiles, busyboxExecutor, logger)
    }

    // A filesystem that a real extraction would have produced.
    private fun createExtractedFilesystem() {
        File(filesystemRoot, "bin").mkdirs()
        File(filesystemRoot, "bin/sh").createNewFile()
        File(filesystemRoot, "etc").mkdirs()
        File(filesystemRoot, "etc/passwd").createNewFile()
        userHome.mkdirs()
        listOf("nosudo", "userland_profile.sh", "ld.so.preload").forEach {
            File(supportDirectory, it).createNewFile()
        }
    }

    private fun createDownloadedArchive() {
        archive.writeText("gzip bytes")
    }

    private fun stubArchiveListing(vararg members: String) {
        whenever(
            busyboxExecutor.runHostApplet(
                eq("tar"),
                argThat { contains("-tzf") },
                any()
            )
        ).thenAnswer { invocation ->
            @Suppress("UNCHECKED_CAST")
            val listener = invocation.getArgument<(String) -> Any>(2)
            members.forEach { listener(it) }
            SuccessfulExecution
        }
    }

    private fun stubExtraction(result: ExecutionResult, extracted: Boolean = true) {
        whenever(
            busyboxExecutor.runHostApplet(
                eq("tar"),
                argThat { contains("-xzvf") },
                any()
            )
        ).thenAnswer {
            if (extracted) createExtractedFilesystem()
            result
        }
    }

    private fun stubUserCreation(result: ExecutionResult) {
        whenever(
            busyboxExecutor.executeProotCommand(
                eq("/support/common/addNonRootUser.sh"),
                eq(filesystemId),
                eq(true),
                any(),
                any(),
                anyOrNull()
            )
        ).thenReturn(result)
    }

    private fun extract(): ExecutionResult = runBlocking {
        filesystemManager.extractFilesystem(filesystem, statelessListener)
    }

    @Test
    fun successMarkerWithoutShellIsNotSuccessful() {
        successMarker.createNewFile()

        assertFalse(filesystemManager.hasFilesystemBeenSuccessfullyExtracted(filesystemId))
    }

    @Test
    fun verifiedFilesystemWithMarkerIsSuccessful() {
        createExtractedFilesystem()
        successMarker.createNewFile()

        assertTrue(filesystemManager.hasFilesystemBeenSuccessfullyExtracted(filesystemId))
        assertTrue(filesystemManager.hasUsableFilesystem(filesystemId, username))
    }

    @Test
    fun verifiedFilesystemWithoutMarkerIsNotSuccessful() {
        createExtractedFilesystem()

        assertFalse(filesystemManager.hasFilesystemBeenSuccessfullyExtracted(filesystemId))
    }

    @Test
    fun missingUserHomeIsNotUsableForThatUser() {
        createExtractedFilesystem()
        userHome.delete()
        successMarker.createNewFile()

        assertFalse(filesystemManager.hasUsableFilesystem(filesystemId, username))
        // The anchors that do not depend on a user remain satisfied.
        assertTrue(filesystemManager.hasUsableFilesystem(filesystemId))
    }

    @Test
    fun missingSupportAnchorDoesNotInvalidateAnExtractedFilesystem() {
        createExtractedFilesystem()
        File(supportDirectory, "ld.so.preload").delete()
        successMarker.createNewFile()

        // copyAssetsToFilesystem restores support files, so a missing one must not
        // cost the user another root-filesystem download.
        assertTrue(filesystemManager.hasUsableFilesystem(filesystemId, username))
    }

    @Test
    fun missingSupportAnchorFailsExtraction() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(SuccessfulExecution)
        stubUserCreation(SuccessfulExecution)
        whenever(
            busyboxExecutor.executeProotCommand(
                eq("/support/common/addNonRootUser.sh"),
                eq(filesystemId),
                eq(true),
                any(),
                any(),
                anyOrNull()
            )
        ).thenAnswer {
            // proot cannot bind a support file that was never copied in.
            File(supportDirectory, "ld.so.preload").delete()
            SuccessfulExecution
        }

        val result = extract()

        assertTrue(result is FailedExecution)
        assertFalse(successMarker.exists())
        assertTrue(failureMarker.exists())
    }

    @Test
    fun traversalMemberFailsBeforeExtraction() {
        createDownloadedArchive()
        stubArchiveListing("etc/passwd", "../../escape")

        val result = extract()

        assertTrue(result is FailedExecution)
        assertFalse(successMarker.exists())
        assertTrue(failureMarker.exists())
        verify(busyboxExecutor, never()).runHostApplet(
            eq("tar"),
            argThat { contains("-xzvf") },
            any()
        )
    }

    @Test
    fun absoluteMemberFailsBeforeExtraction() {
        createDownloadedArchive()
        stubArchiveListing("etc/passwd", "/etc/shadow")

        val result = extract()

        assertTrue(result is FailedExecution)
        assertFalse(successMarker.exists())
        verify(busyboxExecutor, never()).runHostApplet(
            eq("tar"),
            argThat { contains("-xzvf") },
            any()
        )
    }

    @Test
    fun missingArchiveFailsWithoutReadingIt() {
        val result = extract()

        assertTrue(result is FailedExecution)
        assertFalse(successMarker.exists())
        verify(busyboxExecutor, never()).runHostApplet(any(), any(), any())
    }

    @Test
    fun unreadableArchiveIsRejected() {
        createDownloadedArchive()
        whenever(
            busyboxExecutor.runHostApplet(eq("tar"), argThat { contains("-tzf") }, any())
        ).thenReturn(FailedExecution("gzip: invalid magic"))

        val result = filesystemManager.validateRootfsArchive(archive)

        assertTrue(result is FailedExecution)
    }

    @Test
    fun emptyArchiveIsRejected() {
        createDownloadedArchive()
        stubArchiveListing()

        assertTrue(filesystemManager.validateRootfsArchive(archive) is FailedExecution)
    }

    @Test
    fun safeArchiveIsAccepted() {
        createDownloadedArchive()
        stubArchiveListing("./", "bin/sh", "etc/passwd", "home/")

        assertEquals(SuccessfulExecution, filesystemManager.validateRootfsArchive(archive))
    }

    @Test
    fun userCreationFailureCannotWriteSuccess() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(SuccessfulExecution)
        stubUserCreation(FailedExecution("useradd failed"))

        val result = extract()

        assertEquals(FailedExecution("useradd failed"), result)
        assertFalse(successMarker.exists())
        assertTrue(failureMarker.exists())
    }

    @Test
    fun extractionFailureCannotWriteSuccess() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(FailedExecution("tar: short read"), extracted = false)

        val result = extract()

        assertEquals(FailedExecution("tar: short read"), result)
        assertFalse(successMarker.exists())
        verify(busyboxExecutor, never()).executeProotCommand(
            any(), any(), any(), any(), any(), anyOrNull()
        )
    }

    @Test
    fun missingAnchorAfterUserCreationCannotWriteSuccess() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        // The stage results are successful but the filesystem never materializes.
        stubExtraction(SuccessfulExecution, extracted = false)
        stubUserCreation(SuccessfulExecution)

        val result = extract()

        assertTrue(result is FailedExecution)
        assertFalse(successMarker.exists())
        assertTrue(failureMarker.exists())
    }

    @Test
    fun failureRetainsTheArchiveForRetry() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(SuccessfulExecution)
        stubUserCreation(FailedExecution("useradd failed"))

        extract()

        assertTrue(archive.exists())
    }

    @Test
    fun verifiedExtractionRemovesTheArchiveAndWritesSuccess() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(SuccessfulExecution)
        stubUserCreation(SuccessfulExecution)

        val result = extract()

        assertEquals(SuccessfulExecution, result)
        assertTrue(successMarker.exists())
        assertFalse(failureMarker.exists())
        assertFalse(archive.exists())
        assertTrue(filesystemManager.hasUsableFilesystem(filesystemId, username))
    }

    @Test
    fun extractionCreatesTheUserThroughProot() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(SuccessfulExecution)
        stubUserCreation(SuccessfulExecution)

        extract()

        verify(busyboxExecutor).executeProotCommand(
            eq("/support/common/addNonRootUser.sh"),
            eq(filesystemId),
            eq(true),
            argThat {
                this["INITIAL_USERNAME"] == username &&
                    this["INITIAL_PASSWORD"] == "password" &&
                    this["INITIAL_VNC_PASSWORD"] == "vncpass"
            },
            any(),
            anyOrNull()
        )
    }

    @Test
    fun extractionUnpacksIntoTheFilesystemDirectoryWithoutBindMounts() {
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(SuccessfulExecution)
        stubUserCreation(SuccessfulExecution)

        extract()

        verify(busyboxExecutor).runHostApplet(
            eq("tar"),
            argThat {
                this[0] == "-xzvf" &&
                    this[1] == archive.absolutePath &&
                    this[2] == "-C" &&
                    this[3] == filesystemRoot.absolutePath &&
                    // Every exclusion covers both stored member shapes, or an
                    // archive rolled as "./name" overwrites the support directory.
                    listOf(
                        "support", "dev", "etc/ld.so.preload",
                        "etc/profile.d/userland_profile.sh", "usr/local/bin/sudo"
                    ).all { excluded ->
                        windowed(2).contains(listOf("--exclude", excluded)) &&
                            windowed(2).contains(listOf("--exclude", "./$excluded"))
                    }
            },
            any()
        )
    }

    @Test
    fun repairPreservesExistingHomeFile() {
        createExtractedFilesystem()
        // A damaged r2 install: the marker is present but the filesystem is not usable.
        successMarker.delete()
        val userFile = File(userHome, "notes.txt")
        userFile.writeText("keep")
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(SuccessfulExecution)
        stubUserCreation(SuccessfulExecution)

        extract()

        assertTrue(userFile.exists())
        assertEquals("keep", userFile.readText())
    }

    @Test
    fun repairClearsAStaleSuccessMarkerBeforeWorkBegins() {
        successMarker.createNewFile()
        createDownloadedArchive()
        stubArchiveListing("bin/sh", "etc/passwd")
        stubExtraction(FailedExecution("tar: short read"), extracted = false)

        extract()

        assertFalse(successMarker.exists())
        assertTrue(failureMarker.exists())
    }
}
