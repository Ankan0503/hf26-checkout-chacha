package dev.ankan.chacha

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

/** Collects the text of the current screen, top to bottom. Nothing else. */
object Screen {

    /** [visible] is false for text scrolled out of view; the brain uses it only as a fallback. */
    data class Line(val text: String, val y: Int, val h: Int, val clickable: Boolean, val visible: Boolean) {
        fun toJson(): JSONObject =
            JSONObject().put("t", text).put("y", y).put("h", h).put("c", clickable).put("v", visible)
    }

    private const val MAX_LINES = 600
    private val WHITESPACE = Regex("\\s+")

    fun read(root: AccessibilityNodeInfo): List<Line> {
        val out = ArrayList<Line>()
        val seen = HashSet<String>()
        val rect = Rect()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.addLast(root)
        while (stack.isNotEmpty() && out.size < MAX_LINES) {
            val node = stack.removeLast()
            val label = (node.text ?: node.contentDescription)?.toString()?.replace(WHITESPACE, " ")?.trim()
            if (!label.isNullOrEmpty()) {
                node.getBoundsInScreen(rect)
                if (seen.add("$label@${rect.top}")) {
                    out += Line(label.take(300), rect.top, rect.height(), node.isClickable, node.isVisibleToUser)
                }
            }
            // Push children in reverse so the first child is read first.
            for (i in node.childCount - 1 downTo 0) node.getChild(i)?.let { stack.addLast(it) }
        }
        return out.sortedBy { it.y }
    }
}
