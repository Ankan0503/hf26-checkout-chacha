package dev.ankan.chacha

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** The last few things the service did, shown in the app so you can debug without a cable. */
object Journal {
    private const val MAX = 12

    fun add(context: Context, line: String) {
        val stamp = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        val lines = (listOf("$stamp  $line") + read(context)).take(MAX)
        prefs(context).edit().putString("journal", lines.joinToString("\n")).apply()
    }

    fun read(context: Context): List<String> =
        prefs(context).getString("journal", "").orEmpty().lines().filter { it.isNotBlank() }

    private fun prefs(context: Context) = context.getSharedPreferences("chacha", Context.MODE_PRIVATE)
}
