package dev.ankan.chacha

import android.content.Context

/** The laptop's address and the pairing code. Stored only on this phone. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("chacha", Context.MODE_PRIVATE)

    var brain: String
        get() = sp.getString("brain", "").orEmpty().trim().removePrefix("http://").trimEnd('/')
        set(value) = sp.edit().putString("brain", value.trim()).apply()

    var code: String
        get() = sp.getString("code", "").orEmpty().trim().uppercase()
        set(value) = sp.edit().putString("code", value.trim()).apply()

    /** Debug only: send every settled screen to the laptop so the parser can be tuned. */
    val trace: Boolean
        get() = sp.getBoolean("trace", false)
}
