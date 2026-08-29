package tech.ula.library.utils

import java.util.concurrent.CopyOnWriteArrayList

/**
 * In-process delivery of download outcomes from the service to whatever is showing
 * setup.
 *
 * The service and the activity share a process, so a listener registry does the
 * whole job that a local broadcast would, without the deprecated dependency or the
 * Intent round trip. Delivery is best effort by design: the journal, not this, is
 * the source of truth, so a listener that was not registered when an outcome
 * arrived recovers by reading state rather than by replaying signals.
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
