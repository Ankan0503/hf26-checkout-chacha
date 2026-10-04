package dev.ankan.chacha

import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Pairing screen: the laptop's address, the pairing code, and a shortcut to Accessibility settings. */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var status: TextView
    private lateinit var journal: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        val pad = (20 * resources.displayMetrics.density).toInt()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
        }
        root.addView(TextView(this).apply {
            text = getString(R.string.app_name)
            textSize = 26f
            typeface = Typeface.DEFAULT_BOLD
        })
        root.addView(TextView(this).apply {
            text = "Judges your cart on Amazon and Flipkart. Everything it sees goes only to your own laptop."
            setPadding(0, pad / 2, 0, pad)
        })

        val brain = field("Laptop address, e.g. 192.168.1.5:8765", prefs.brain, InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        val code = field("Pairing code shown on the laptop", prefs.code, InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS)
        root.addView(brain)
        root.addView(code)

        root.addView(Button(this).apply {
            text = "Save and test connection"
            setOnClickListener {
                prefs.brain = brain.text.toString()
                prefs.code = code.text.toString()
                status.text = "Testing…"
                BrainClient(this@MainActivity).health { result ->
                    status.text = result.fold(
                        { if (it.optBoolean("paired")) "Connected to your laptop ✓" else "Laptop found, but the pairing code is wrong." },
                        { it.message ?: "Couldn't connect." },
                    )
                }
            }
        })
        root.addView(Button(this).apply {
            text = "Turn Chacha on (Accessibility)"
            setOnClickListener { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        })

        status = TextView(this).apply { setPadding(0, pad / 2, 0, pad / 2) }
        root.addView(status)
        root.addView(TextView(this).apply {
            text = "Recent activity"
            typeface = Typeface.DEFAULT_BOLD
        })
        journal = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            textSize = 12f
        }
        root.addView(journal)

        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onResume() {
        super.onResume()
        status.text = if (serviceEnabled()) "Chacha is ON. Open Amazon or Flipkart." else "Chacha is OFF. Tap 'Turn Chacha on'."
        journal.text = Journal.read(this).joinToString("\n").ifEmpty { "Nothing yet." }
    }

    private fun serviceEnabled(): Boolean {
        val enabled = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
        val me = ComponentName(this, ChachaService::class.java)
        val names = setOf(me.flattenToString(), me.flattenToShortString())
        return enabled.split(':').any { entry -> names.any { it.equals(entry, ignoreCase = true) } }
    }

    private fun field(hint: String, value: String, type: Int) = EditText(this).apply {
        this.hint = hint
        setText(value)
        inputType = type
        isSingleLine = true
    }
}
