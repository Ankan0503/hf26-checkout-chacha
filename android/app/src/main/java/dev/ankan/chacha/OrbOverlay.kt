package dev.ankan.chacha

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import kotlin.math.abs

/**
 * Owns the two overlay windows: the orb and the verdict card.
 *
 * Accessibility overlays need no "draw over other apps" permission; the
 * accessibility service itself is the permission.
 */
class OrbOverlay(
    private val service: AccessibilityService,
    private val onTap: () -> Unit,
    private val onLongPress: () -> Unit,
    private val onDecision: (decision: String, verdict: JSONObject) -> Unit,
) {
    private val wm = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val dm = service.resources.displayMetrics
    private val themed = ContextThemeWrapper(service, android.R.style.Theme_Material)
    private val main = Handler(Looper.getMainLooper())

    private val orb = OrbView(service)
    private val orbParams = overlayParams(dp(96), dp(96)).apply {
        gravity = Gravity.TOP or Gravity.START
        x = dm.widthPixels - dp(100)
        y = (dm.heightPixels * 0.3f).toInt() // Above the card, which sits at the bottom.
    }

    private var card: View? = null

    var shown = false
        private set
    val cardShowing get() = card != null

    init {
        orb.setOnTouchListener(DragOrTap())
    }

    fun show() {
        if (shown) return
        orb.mood = Mood.IDLE
        wm.addView(orb, orbParams)
        shown = true
    }

    fun hide() {
        hideCard()
        if (!shown) return
        wm.removeView(orb)
        shown = false
    }

    fun thinking() {
        hideCard()
        orb.mood = Mood.THINKING
    }

    /** "quiet" means nothing worth saying: back to idle. "card": false means change colour only. */
    fun showVerdict(verdict: JSONObject) {
        if (verdict.optBoolean("quiet")) {
            hideCard()
            orb.mood = Mood.IDLE
            return
        }
        orb.mood = Mood.from(verdict.optString("mood"))
        if (verdict.optBoolean("card", true)) showCard(verdict)
    }

    fun showError(message: String) {
        orb.mood = Mood.ERROR
        showCard(JSONObject().put("mood", "error").put("title", Mood.ERROR.label).put("line", message))
    }

    fun hideCard() {
        card?.let { wm.removeView(it) }
        card = null
    }

    private fun showCard(verdict: JSONObject) {
        hideCard()
        if (!shown) return
        val mood = Mood.from(verdict.optString("mood"))

        val box = LinearLayout(themed).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(16), dp(18), dp(14))
            background = GradientDrawable().apply {
                cornerRadius = dp(22).toFloat()
                setColor(Color.argb(242, 18, 18, 24))
                setStroke(dp(2), mood.core)
            }
        }
        box.addView(label(verdict.optString("title", mood.label), 13f, mood.glow, bold = true))
        box.addView(label(verdict.optString("line"), 18f, Color.WHITE).apply { setPadding(0, dp(6), 0, dp(6)) })

        val facts = verdict.optJSONArray("facts")
        if (facts != null && facts.length() > 0) {
            val lines = (0 until facts.length()).joinToString("\n") { "• " + facts.optString(it) }
            box.addView(label(lines, 13f, Color.argb(205, 220, 220, 230)))
        }

        if (verdict.optBoolean("actionable", false)) {
            val row = LinearLayout(themed).apply {
                orientation = LinearLayout.HORIZONTAL
                setPadding(0, dp(12), 0, 0)
            }
            listOf("removed" to "Remove it", "sleep" to "Sleep on it", "buy" to "Buy anyway").forEach { (decision, text) ->
                row.addView(
                    Button(themed).apply {
                        this.text = text
                        isAllCaps = false
                        textSize = 13f
                        setOnClickListener {
                            onDecision(decision, verdict)
                            hideCard()
                            orb.mood = Mood.IDLE
                        }
                    },
                    LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
                )
            }
            box.addView(row)
        }

        box.setOnClickListener { hideCard() }

        val params = overlayParams(minOf(dm.widthPixels - dp(24), dp(420)), WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = dp(96)
        }
        wm.addView(box, params)
        card = box

        // Cards without decisions to make go away on their own.
        if (!verdict.optBoolean("actionable", false)) {
            main.postDelayed({ if (card === box) hideCard() }, CARD_SECONDS * 1000L)
        }
    }

    private fun label(text: String, sp: Float, color: Int, bold: Boolean = false) = TextView(themed).apply {
        this.text = text
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun overlayParams(width: Int, height: Int) = WindowManager.LayoutParams(
        width,
        height,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    )

    private fun dp(value: Int) = (value * dm.density).toInt()

    private companion object {
        const val CARD_SECONDS = 9
    }

    /** Drag to move, tap to ask, long-press to send a debug dump. */
    private inner class DragOrTap : View.OnTouchListener {
        private val slop = ViewConfiguration.get(service).scaledTouchSlop
        private var downX = 0f
        private var downY = 0f
        private var startX = 0
        private var startY = 0
        private var dragging = false
        private var longPressed = false
        private val longPress = Runnable {
            longPressed = true
            onLongPress()
        }

        override fun onTouch(view: View, event: MotionEvent): Boolean {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX
                    downY = event.rawY
                    startX = orbParams.x
                    startY = orbParams.y
                    dragging = false
                    longPressed = false
                    main.postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong())
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downX
                    val dy = event.rawY - downY
                    if (!dragging && (abs(dx) > slop || abs(dy) > slop)) {
                        dragging = true
                        main.removeCallbacks(longPress)
                    }
                    if (dragging) {
                        orbParams.x = startX + dx.toInt()
                        orbParams.y = startY + dy.toInt()
                        wm.updateViewLayout(orb, orbParams)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    main.removeCallbacks(longPress)
                    if (!dragging && !longPressed) onTap()
                }
                MotionEvent.ACTION_CANCEL -> main.removeCallbacks(longPress)
            }
            return true
        }
    }
}
