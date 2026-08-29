package tech.ula.library.utils

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.InputStream

sealed class ExecutionResult
data class MissingExecutionAsset(val asset: String) : ExecutionResult()
object SuccessfulExecution : ExecutionResult()
data class FailedExecution(val reason: String) : ExecutionResult()
data class OngoingExecution(val process: Process) : ExecutionResult()

class BusyboxExecutor(
    private val ulaFiles: UlaFiles,
    private val prootDebugLogger: ProotDebugLogger,
    private val busyboxWrapper: BusyboxWrapper = BusyboxWrapper(ulaFiles)
) {

    private val discardOutput: (String) -> Any = { }

    fun executeScript(
        scriptCall: String,
        listener: (String) -> Any = discardOutput
    ): ExecutionResult {
        val updatedCommand = busyboxWrapper.wrapScript(scriptCall)

        return runCommand(updatedCommand, listener)
    }

    fun executeCommand(
        command: String,
        listener: (String) -> Any = discardOutput
    ): ExecutionResult {
        val updatedCommand = busyboxWrapper.wrapCommand(command)

        return runCommand(updatedCommand, listener)
    }

    fun runHostApplet(
        applet: String,
        args: List<String>,
        listener: (String) -> Any = discardOutput
    ): ExecutionResult {
        return runCommand(busyboxWrapper.wrapHostApplet(applet, args), listener)
    }

    private fun runCommand(
        command: List<String>,
        listener: (String) -> Any
    ): ExecutionResult {
        if (!busyboxWrapper.busyboxIsPresent()) {
            return MissingExecutionAsset("busybox")
        }

        val env = busyboxWrapper.getBusyboxEnv()
        val processBuilder = ProcessBuilder(command)
        processBuilder.directory(ulaFiles.filesDir)
        processBuilder.environment().putAll(env)
        processBuilder.redirectErrorStream(true)

        return try {
            val process = processBuilder.start()
            collectOutput(process.inputStream, listener)
            getProcessResult(process)
        } catch (err: Exception) {
            FailedExecution("$err")
        }
    }

    fun executeProotCommand(
        command: String,
        filesystemDirName: String,
        commandShouldTerminate: Boolean,
        env: HashMap<String, String> = hashMapOf(),
        listener: (String) -> Any = discardOutput,
        coroutineScope: CoroutineScope = CoroutineScope(Dispatchers.IO)
    ): ExecutionResult {
        when {
            !busyboxWrapper.busyboxIsPresent() ->
                return MissingExecutionAsset("busybox")
            !busyboxWrapper.prootIsPresent() ->
                return MissingExecutionAsset("proot")
            !busyboxWrapper.executionScriptIsPresent() ->
                return MissingExecutionAsset("execution script")
        }

        val prootDebugEnabled = prootDebugLogger.isEnabled
        val prootDebugLevel =
            if (prootDebugEnabled) prootDebugLogger.verbosityLevel else "-1"

        val updatedCommand = busyboxWrapper.addBusyboxAndProot(command)
        val filesystemDir = File("${ulaFiles.filesDir.absolutePath}/$filesystemDirName")

        env.putAll(busyboxWrapper.getProotEnv(env, filesystemDir, prootDebugLevel))

        val processBuilder = ProcessBuilder(updatedCommand)
        processBuilder.directory(ulaFiles.filesDir)
        processBuilder.environment().putAll(env)
        processBuilder.redirectErrorStream(true)

        return try {
            val process = processBuilder.start()
            when {
                prootDebugEnabled && commandShouldTerminate -> {
                    listener("Output redirecting to proot debug log")
                    prootDebugLogger.logStream(process.inputStream, coroutineScope)
                    getProcessResult(process)
                }
                prootDebugEnabled && !commandShouldTerminate -> {
                    listener("Output redirecting to proot debug log")
                    prootDebugLogger.logStream(process.inputStream, coroutineScope)
                    OngoingExecution(process)
                }
                commandShouldTerminate -> {
                    collectOutput(process.inputStream, listener)
                    getProcessResult(process)
                }
                else -> {
                    OngoingExecution(process)
                }
            }
        } catch (err: Exception) {
            FailedExecution("$err")
        }
    }

    suspend fun recursivelyDelete(
        absolutePath: String
    ): ExecutionResult = withContext(Dispatchers.IO) {
        val command = "rm -rf $absolutePath"
        return@withContext executeCommand(command)
    }

    private fun collectOutput(inputStream: InputStream, listener: (String) -> Any) {
        val buf = inputStream.bufferedReader(Charsets.UTF_8)

        buf.forEachLine { listener(it) }

        buf.close()
    }

    private fun getProcessResult(process: Process): ExecutionResult {
        return if (process.waitFor() == 0) SuccessfulExecution
        else FailedExecution("Command failed with: ${process.exitValue()}")
    }
}

// This class is intended to allow stubbing of elements that are unavailable during unit tests.
class BusyboxWrapper(private val ulaFiles: UlaFiles) {
    val hostBusybox: File = File(ulaFiles.supportDir, "busybox_static")

    // For basic commands, CWD should be `applicationFilesDir`.
    fun wrapCommand(command: String): List<String> {
        return listOf(hostBusybox.path, "sh", "-c", command)
    }

    fun wrapScript(command: String): List<String> {
        return listOf(hostBusybox.path, "sh") + command.split(" ")
    }

    fun wrapHostApplet(applet: String, args: List<String>): List<String> {
        return listOf(hostBusybox.path, applet) + args
    }

    fun getBusyboxEnv(): HashMap<String, String> {
        return hashMapOf(
            "LD_LIBRARY_PATH" to ulaFiles.supportDir.absolutePath,
            "LIB_PATH" to ulaFiles.supportDir.absolutePath,
            "ROOT_PATH" to ulaFiles.filesDir.absolutePath
        )
    }

    fun busyboxIsPresent(): Boolean {
        return hostBusybox.exists()
    }

    // Proot scripts expect CWD to be `applicationFilesDir/<filesystem`.
    fun addBusyboxAndProot(command: String): List<String> {
        return listOf(
            hostBusybox.absolutePath,
            "sh",
            "support/execInProot.sh"
        ) + command.split(" ")
    }

    fun getProotEnv(
        env: HashMap<String, String> = hashMapOf(),
        filesystemDir: File,
        prootDebugLevel: String
    ): HashMap<String, String> {
        val emulatedStorageBinding =
            "-b ${ulaFiles.emulatedUserDir.absolutePath}:/storage/internal"
        val externalStorageBinding = ulaFiles.sdCardUserDir?.run {
            "-b ${this.absolutePath}:/storage/sdcard"
        } ?: ""
        val sdcardBinding = ulaFiles.sdcardDir?.run {
            "-b ${this.absolutePath}:/sdcard"
        } ?: ""
        val documentsBinding = ulaFiles.documentsDir?.run {
            "-b ${this.absolutePath}:/Documents"
        } ?: ""
        val downloadsBinding = ulaFiles.downloadDir?.run {
            "-b ${this.absolutePath}:/Downloads"
        } ?: ""
        val musicBinding = ulaFiles.musicDir?.run {
            "-b ${this.absolutePath}:/Music"
        } ?: ""
        val picturesBinding = ulaFiles.picturesDir?.run {
            "-b ${this.absolutePath}:/Pictures"
        } ?: ""
        val videosBinding = ulaFiles.videosDir?.run {
            "-b ${this.absolutePath}:/Videos"
        } ?: ""
        val dcimBinding = ulaFiles.DCIMDir?.run {
            "-b ${this.absolutePath}:/DCIM"
        } ?: ""

        val intentsBinding = "-b ${ulaFiles.intentsDir}:/Intents"
        val bindings = listOf(
            emulatedStorageBinding,
            externalStorageBinding,
            sdcardBinding,
            documentsBinding,
            downloadsBinding,
            musicBinding,
            picturesBinding,
            videosBinding,
            dcimBinding,
            intentsBinding
        ).filter { it.isNotBlank() }.joinToString(" ")
        return hashMapOf(
            "LD_LIBRARY_PATH" to ulaFiles.supportDir.absolutePath,
            "LIB_PATH" to ulaFiles.supportDir.absolutePath,
            "ROOT_PATH" to ulaFiles.filesDir.absolutePath,
            "ROOTFS_PATH" to filesystemDir.absolutePath,
            "PROOT_DEBUG_LEVEL" to prootDebugLevel,
            "EXTRA_BINDINGS" to bindings,
            "OS_VERSION" to System.getProperty("os.version")!!
        )
    }

    fun prootIsPresent(): Boolean {
        return ulaFiles.proot.exists()
    }

    fun executionScriptIsPresent(): Boolean {
        val execInProotFile = File(ulaFiles.supportDir, "execInProot.sh")
        return execInProotFile.exists()
    }
}
