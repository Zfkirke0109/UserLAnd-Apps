package tech.ula.library.utils

import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.ImageView
import android.widget.TextView
import tech.ula.library.R

/**
 * The card that credits the creator of the app this launcher was built from and
 * offers a way to pay them for it.
 *
 * It appears once, after a session has actually started, so it never interrupts
 * setup or a repair, and it stays available from About & Support for good. The
 * decision of when to show lives in [CreatorSupportPolicy], which is plain
 * Kotlin; this class is the dialog and the intents.
 */
class CreatorSupportPrompter(private val activity: Activity) {

    private val policy = CreatorSupportPolicy(SharedPreferenceSupportState(activity))

    /** Called only once a session has really started. */
    fun showAfterFirstSuccessfulSession() {
        if (policy.shouldShowAutomatically()) show()
    }

    fun showFromMenu() {
        if (policy.shouldShowFromMenu()) show()
    }

    private fun show() {
        val view = activity.layoutInflater.inflate(R.layout.dia_creator_support, null)
        // The message names the app, so it is filled in here rather than bound
        // statically in the layout, which cannot substitute a format argument.
        view.findViewById<TextView>(R.id.creator_support_message).text =
            activity.getString(
                R.string.creator_support_message,
                activity.getString(R.string.app_name)
            )
        view.findViewById<ImageView>(R.id.creator_support_badge).setOnClickListener {
            openListing(activity.packageName)
        }
        AlertDialog.Builder(activity)
            .setTitle(R.string.creator_support_title)
            .setView(view)
            .setPositiveButton(R.string.button_ok) { dialog, _ -> dialog.dismiss() }
            .create()
            .show()
    }

    /**
     * Opens the Play listing. The market URI goes straight to the installed Play
     * app; a device without it still has to reach the listing, so the HTTPS form
     * is the fallback rather than a dead end.
     */
    fun openListing(packageName: String) {
        val market = Intent(Intent.ACTION_VIEW, Uri.parse(CreatorLinks.market(packageName)))
        try {
            activity.startActivity(market)
        } catch (err: ActivityNotFoundException) {
            val web = Intent(Intent.ACTION_VIEW, Uri.parse(CreatorLinks.web(packageName)))
            try {
                activity.startActivity(web)
            } catch (err: ActivityNotFoundException) {
                // No browser either. Saying nothing is better than crashing.
            }
        }
    }
}

private class SharedPreferenceSupportState(context: Context) : SupportPromptState {

    private val preferences =
        context.getSharedPreferences("creatorSupport", Context.MODE_PRIVATE)

    override fun hasBeenShown(): Boolean = preferences.getBoolean(KEY, false)

    override fun markShown() {
        preferences.edit().putBoolean(KEY, true).apply()
    }

    private companion object {
        const val KEY = "creatorSupportCardShown"
    }
}
