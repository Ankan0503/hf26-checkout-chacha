package dev.ankan.chacha

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.accessibility.AccessibilityEvent
import org.json.JSONArray
import org.json.JSONObject

/**
 * Watches only the shopping apps listed in res/xml/chacha_accessibility.xml.
 * Android delivers events from those packages and nothing else.
 *
 * The phone is deliberately simple: it sends the text of the screen to the
 * brain on the laptop, which does all the parsing and judging. The parser can
 * then be fixed without rebuilding the app.
 */
class ChachaService : AccessibilityService() {

    private val main = Handler(Looper.getMainLooper())
    private lateinit var orb: OrbOverlay
    private lateinit var brain: BrainClient
    private lateinit var prefs: Prefs
    private var allowed: Set<String> = emptySet()
    private var nullPolls = 0
    private var inFlight = false

    // The last product page that still offered "Add to cart" (see [settled]).
    private var productScreen: List<Screen.Line>? = null
    private var productScreenAt = 0L
    private var lastAddAt = 0L
    private var lastCartSignature: String? = null

    override fun onServiceConnected() {
        allowed = serviceInfo?.packageNames?.toSet().orEmpty()
        prefs = Prefs(this)
        brain = BrainClient(this)
        orb = OrbOverlay(
            this,
            onTap = { if (orb.cardShowing) orb.hideCard() else look("manual") },
            onLongPress = { look("dump") },
            onDecision = { decision, verdict -> brain.feedback(decision, verdict) },
        )
        Journal.add(this, "service on, watching ${allowed.size} apps")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        val pkg = event.packageName?.toString() ?: return
        if (pkg !in allowed) return

        if (!orb.shown) {
            orb.show()
            main.removeCallbacks(watcher)
            main.postDelayed(watcher, 1000)
        }

        when (event.eventType) {
            // Apps with native buttons (Amazon) report the tap itself.
            AccessibilityEvent.TYPE_VIEW_CLICKED -> {
                val label = labelOf(event)
                if (ADD_TO_CART_TAP.containsMatchIn(label)) {
                    Journal.add(this, "tapped: $label")
                    val snapshot = productScreen
                    main.postDelayed({ addedToCart(pkg, snapshot, "tap") }, 500)
                }
            }
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> {
                main.removeCallbacks(settled)
                main.postDelayed(settled, SETTLE_MS)
            }
        }
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        if (::orb.isInitialized) orb.hide()
        super.onDestroy()
    }

    /** Hides the orb once you leave the allowed apps. Reads only the package name. */
    private val watcher = object : Runnable {
        override fun run() {
            if (!orb.shown) return
            val pkg = rootInActiveWindow?.packageName?.toString()
            when {
                pkg == null -> if (++nullPolls >= 3) orb.hide()
                pkg == packageName || pkg in allowed -> nullPolls = 0
                else -> orb.hide()
            }
            if (orb.shown) main.postDelayed(this, 1000) else nullPolls = 0
        }
    }

    /**
     * Runs once the screen stops changing.
     *
     * Flipkart's buttons never report taps to Android, so an add is detected by
     * what the screen does next: on the same product page, "Add to cart" turns
     * into "Go to cart", or an "added to cart" message appears.
     */
    private val settled = Runnable {
        val root = rootInActiveWindow ?: return@Runnable
        val pkg = root.packageName?.toString() ?: return@Runnable
        if (pkg !in allowed) return@Runnable
        val lines = Screen.read(root)
        val onScreen = lines.filter { it.visible }
        val now = SystemClock.uptimeMillis()

        if (prefs.trace) brain.see(payload("trace", pkg, lines, null)) {}

        // A product page offers "Add to cart" next to "Buy now". Upsell sheets ("Protect your
        // device", "SKIP / Add to cart") and carousels have "Add to cart" without "Buy now",
        // so they never replace the product we're watching.
        val productPage = onScreen.any { ADD_BUTTON.matches(it.text) } && onScreen.any { BUY_NOW.matches(it.text) }
        val added = onScreen.any { GO_TO_CART.matches(it.text) || ADDED.containsMatchIn(it.text) }
        val remembered = productScreen
        when {
            productPage && !added -> {
                productScreen = lines
                productScreenAt = now
            }
            added && remembered != null && now - productScreenAt < PRODUCT_MEMORY_MS && sameScreen(remembered, lines) -> {
                addedToCart(pkg, lines, "screen")
                return@Runnable
            }
        }

        // The cart: judged once per distinct total, not on every scroll. Flipkart keeps
        // "Total Amount" below the fold and shows the total only beside "Proceed to buy".
        val totalAt = lines.indexOfFirst { TOTAL.containsMatchIn(it.text) }
        val checkoutAt = onScreen.indexOfFirst { CHECKOUT.containsMatchIn(it.text) }
        if (totalAt < 0 && checkoutAt < 0) {
            lastCartSignature = null
            return@Runnable
        }
        val signature = if (totalAt >= 0) {
            lines.drop(totalAt).take(3).joinToString("|") { it.text }
        } else {
            onScreen.subList(maxOf(0, checkoutAt - 3), checkoutAt + 1).joinToString("|") { it.text }
        }
        if (signature != lastCartSignature && !inFlight) {
            lastCartSignature = signature
            send("cart_view", pkg, lines, null)
        }
    }

    private fun addedToCart(pkg: String, snapshot: List<Screen.Line>?, how: String) {
        val now = SystemClock.uptimeMillis()
        if (now - lastAddAt < 5000) return // The tap and the screen change report the same add.
        lastAddAt = now
        productScreen = null
        val lines = snapshot ?: rootInActiveWindow?.let { Screen.read(it) } ?: return
        Journal.add(this, "added to cart ($how)")
        send("add_to_cart", pkg, lines, how)
    }

    /** True when most of what was on one screen is still on the other: the same page, changed a little. */
    private fun sameScreen(a: List<Screen.Line>, b: List<Screen.Line>): Boolean {
        val before = a.mapTo(HashSet()) { it.text }
        val after = b.mapTo(HashSet()) { it.text }
        val kept = before.count { it in after }
        return kept >= 0.5 * minOf(before.size, after.size)
    }

    private fun look(kind: String) {
        val root = rootInActiveWindow
        val pkg = root?.packageName?.toString()
        if (root == null || pkg == null || pkg !in allowed) {
            orb.showError("I only look at Amazon and Flipkart. Open one of them first.")
            return
        }
        send(kind, pkg, Screen.read(root), null)
    }

    private fun payload(kind: String, pkg: String, lines: List<Screen.Line>, clicked: String?) = JSONObject()
        .put("app", pkg)
        .put("event", kind)
        .put("clicked", clicked ?: JSONObject.NULL)
        .put("ts", System.currentTimeMillis())
        .put("texts", JSONArray().apply { lines.forEach { put(it.toJson()) } })

    private fun send(kind: String, pkg: String, lines: List<Screen.Line>, clicked: String?) {
        inFlight = true
        orb.thinking()
        brain.see(payload(kind, pkg, lines, clicked)) { result ->
            inFlight = false
            result
                .onSuccess {
                    orb.showVerdict(it)
                    if (!it.optBoolean("quiet")) {
                        Journal.add(this, "$kind -> ${it.optString("mood")}: ${it.optString("line").take(60)}")
                    }
                }
                .onFailure {
                    orb.showError(it.message ?: "No answer from your laptop.")
                    Journal.add(this, "$kind failed: ${it.message}")
                }
        }
    }

    private fun labelOf(event: AccessibilityEvent): String {
        val parts = mutableListOf<CharSequence>()
        parts += event.text.filterNotNull()
        event.contentDescription?.let { parts += it }
        event.source?.let { node ->
            node.text?.let { parts += it }
            node.contentDescription?.let { parts += it }
            for (i in 0 until minOf(node.childCount, 4)) {
                node.getChild(i)?.let { child ->
                    child.text?.let { parts += it }
                    child.contentDescription?.let { parts += it }
                }
            }
        }
        return parts.joinToString(" ").replace(WHITESPACE, " ").trim()
    }

    companion object {
        private const val SETTLE_MS = 700L
        private const val PRODUCT_MEMORY_MS = 120_000L
        private val ADD_TO_CART_TAP = Regex("(?i)add\\s+to\\s+(cart|bag|basket)")
        private val ADD_BUTTON = Regex("(?i)\\s*add to (cart|bag|basket)\\s*")
        private val BUY_NOW = Regex("(?i)\\s*buy now\\s*")
        private val GO_TO_CART = Regex("(?i)\\s*go to (cart|bag|basket)\\s*")
        private val ADDED = Regex("(?i)added to (your )?(cart|bag|basket)|item added")
        private val TOTAL = Regex("(?i)\\bsubtotal\\b|total amount|order total|cart total")
        private val CHECKOUT = Regex("(?i)^\\s*(proceed to (buy|checkout)|place order|checkout)\\b")
        private val WHITESPACE = Regex("\\s+")
    }
}
