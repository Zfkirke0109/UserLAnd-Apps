package tech.ula.library.utils

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class R3CreatorSupportPrompterTest {

    private class RecordingState(private var shown: Boolean = false) : SupportPromptState {
        var writes = 0
        override fun hasBeenShown() = shown
        override fun markShown() {
            shown = true
            writes += 1
        }
    }

    @Test
    fun packageProducesOfficialMarketAndWebUris() {
        assertEquals(
            "market://details?id=tech.ula.andacious",
            CreatorLinks.market("tech.ula.andacious")
        )
        assertEquals(
            "https://play.google.com/store/apps/details?id=tech.ula.andacious",
            CreatorLinks.web("tech.ula.andacious")
        )
    }

    @Test
    fun everyLauncherLinksToItsOwnListing() {
        for (packageName in listOf("tech.ula.foxbox_pro", "tech.ula.gimp", "tech.ula.idle")) {
            assertTrue(CreatorLinks.market(packageName).endsWith(packageName))
            assertTrue(CreatorLinks.web(packageName).endsWith(packageName))
        }
    }

    @Test
    fun automaticCardShowsOnceButMenuAlwaysShows() {
        val state = RecordingState()
        val policy = CreatorSupportPolicy(state)

        assertTrue("the card offers itself once", policy.shouldShowAutomatically())
        assertFalse("and never asks again on its own", policy.shouldShowAutomatically())

        // Deliberately opening it is a different thing entirely.
        assertTrue(policy.shouldShowFromMenu())
        assertTrue(policy.shouldShowFromMenu())
    }

    @Test
    fun theCardIsRememberedAcrossARestart() {
        val state = RecordingState()
        CreatorSupportPolicy(state).shouldShowAutomatically()

        // A new process reading the same stored state must not show it again.
        assertFalse(CreatorSupportPolicy(state).shouldShowAutomatically())
        assertEquals("state is written once, not on every check", 1, state.writes)
    }

    @Test
    fun aPreviouslyShownCardIsNotShownAgain(){
        val policy = CreatorSupportPolicy(RecordingState(shown = true))

        assertFalse(policy.shouldShowAutomatically())
        assertTrue(policy.shouldShowFromMenu())
    }
}
