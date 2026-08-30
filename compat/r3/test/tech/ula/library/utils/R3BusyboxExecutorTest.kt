package tech.ula.library.utils

import com.nhaarman.mockitokotlin2.whenever
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.mockito.Mock
import org.mockito.junit.MockitoJUnitRunner
import java.io.File

@RunWith(MockitoJUnitRunner::class)
class R3BusyboxExecutorTest {

    @get:Rule val tempFolder = TemporaryFolder()

    @Mock lateinit var ulaFiles: UlaFiles

    private lateinit var filesDir: File
    private lateinit var supportDir: File
    private lateinit var wrapper: BusyboxWrapper

    @Before
    fun setUp() {
        filesDir = tempFolder.newFolder("files")
        supportDir = File(filesDir, "support").apply { mkdirs() }
        whenever(ulaFiles.filesDir).thenReturn(filesDir)
        whenever(ulaFiles.supportDir).thenReturn(supportDir)
        wrapper = BusyboxWrapper(ulaFiles)
    }

    @Test
    fun hostCommandsPreferStaticBusybox() {
        assertEquals(File(supportDir, "busybox_static"), wrapper.hostBusybox)
    }

    @Test
    fun everyBusyboxEnvironmentContainsSupportLibraryPath() {
        assertEquals(
            supportDir.absolutePath,
            wrapper.getBusyboxEnv()["LD_LIBRARY_PATH"]
        )
    }

    @Test
    fun hostAppletKeepsArgumentsSeparate() {
        assertEquals(
            listOf(
                File(supportDir, "busybox_static").path,
                "tar",
                "-tzf",
                "name with space.tar.gz"
            ),
            wrapper.wrapHostApplet(
                "tar",
                listOf("-tzf", "name with space.tar.gz")
            )
        )
    }
}
