package tech.ula.library.utils

import java.util.concurrent.CopyOnWriteArrayList

/**
 * In-process delivery of download outcomes from the service to whatever is showing
 * setup.
 *
 * The service and the activity share a process, so a listener registry does the
 * whole job that a local broadcast would, without the deprecated dependency or the
 * Intent round trip. The journal remains the source of truth, but delivery cannot
 * be best effort: a large asset takes minutes, and if the activity is recreated
 * while it downloads, the new listener registers after the batch has already
 * finished. Nothing publishes again, and setup waits for a signal that has been
 * and gone. So the most recent outcome is replayed to a listener when it
 * registers, which is what makes a listener that arrived late still correct.
 */
object AssetDownloadSignals {

    const val ACTION_DOWNLOAD_STATE = "tech.ula.library.DOWNLOAD_STATE"

    fun interface Listener {
        fun onDownloadState(outcome: BatchOutcome)
    }

    class Registration internal constructor(private val listener: Listener) {
        fun cancel() {
            listeners.remove(listener)
        }
    }

    private val listeners = CopyOnWriteArrayList<Listener>()

    @Volatile
    var latest: BatchOutcome = BatchIdle
        private set

    fun observe(listener: Listener): Registration {
        listeners.add(listener)
        // A listener that registers after the batch finished would otherwise
        // never hear about it: publish only reaches listeners present at the
        // time, and a finished batch never publishes again.
        val known = latest
        if (known !is BatchIdle) listener.onDownloadState(known)
        return Registration(listener)
    }

    fun publish(outcome: BatchOutcome) {
        latest = outcome
        listeners.forEach { it.onDownloadState(outcome) }
    }

    /** Exposed for tests and for a clean restart of setup. */
    fun reset() {
        listeners.clear()
        latest = BatchIdle
    }
}
