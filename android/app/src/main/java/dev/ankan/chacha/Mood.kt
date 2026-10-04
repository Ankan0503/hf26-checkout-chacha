package dev.ankan.chacha

import android.graphics.Color

/** What the orb is feeling. Colours: [core] fills the orb, [glow] is the halo and highlight. */
enum class Mood(val core: Int, val glow: Int, val label: String) {
    IDLE(Color.parseColor("#8B7CFF"), Color.parseColor("#6FE3FF"), "Chacha is watching"),
    THINKING(Color.parseColor("#39C6FF"), Color.parseColor("#A6F0FF"), "Chacha is thinking"),
    PRAISE(Color.parseColor("#FFB800"), Color.parseColor("#FFE58A"), "Chacha approves"),
    NORMAL(Color.parseColor("#3D8BFF"), Color.parseColor("#9CC8FF"), "Chacha shrugs"),
    ROAST(Color.parseColor("#FF3B30"), Color.parseColor("#FF9F43"), "Chacha says no"),
    INFO(Color.parseColor("#8B7CFF"), Color.parseColor("#C9C2FF"), "Chacha"),
    ERROR(Color.parseColor("#8E8E93"), Color.parseColor("#C7C7CC"), "Chacha can't reach your laptop");

    companion object {
        fun from(name: String?): Mood = when (name?.lowercase()) {
            "praise" -> PRAISE
            "normal" -> NORMAL
            "roast" -> ROAST
            "idle" -> IDLE
            "error" -> ERROR
            else -> INFO
        }
    }
}
