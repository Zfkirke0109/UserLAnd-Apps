package tech.ula.library.utils

/**
 * Where to send someone who wants to pay the creator of the app this launcher
 * was built from.
 *
 * Both forms are needed: the market URI opens the Play app directly when it is
 * installed, and a device without it still has to reach the listing, so the
 * caller falls back to the HTTPS form.
 */
object CreatorLinks {

    fun market(packageName: String): String = "market://details?id=$packageName"

    fun web(packageName: String): String =
        "https://play.google.com/store/apps/details?id=$packageName"
}

/** Whether the support card has already been shown once on its own. */
interface SupportPromptState {
    fun hasBeenShown(): Boolean
    fun markShown()
}

/**
 * Decides when the support card appears.
 *
 * It offers itself once, after a session has actually started, and never
 * interrupts setup or a repair. After that it is only ever opened deliberately,
 * from the menu, where it stays available for good.
 */
class CreatorSupportPolicy(private val state: SupportPromptState) {

    fun shouldShowAutomatically(): Boolean {
        if (state.hasBeenShown()) return false
        state.markShown()
        return true
    }

    /** The menu entry always opens the card, however many times it is used. */
    fun shouldShowFromMenu(): Boolean = true
}
