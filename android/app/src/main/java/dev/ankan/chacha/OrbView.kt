package dev.ankan.chacha

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sin

/** The glowing orb. Breathes when idle, spins while thinking, flickers when roasting. */
class OrbView(context: Context) : View(context) {

    var mood: Mood = Mood.IDLE
        set(value) {
            field = value
            invalidate()
        }

    private var phase = 0f
    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 2400
        repeatCount = ValueAnimator.INFINITE
        interpolator = LinearInterpolator()
        addUpdateListener {
            phase = it.animatedValue as Float
            invalidate()
        }
    }

    private val halo = Paint(Paint.ANTI_ALIAS_FLAG)
    private val body = Paint(Paint.ANTI_ALIAS_FLAG)
    private val shine = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(110, 255, 255, 255) }
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        animator.start()
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val r = min(width, height) * 0.25f
        val t = phase * 2 * PI

        val pulse = when (mood) {
            Mood.ROAST -> (0.55 + 0.45 * abs(sin(t * 4) * sin(t * 7))).toFloat()
            Mood.THINKING -> (0.7 + 0.3 * sin(t * 2)).toFloat()
            else -> (0.72 + 0.28 * sin(t)).toFloat()
        }

        val haloR = r * (1.5f + 0.4f * pulse)
        halo.shader = RadialGradient(
            cx, cy, haloR,
            intArrayOf(withAlpha(mood.glow, 170 * pulse), withAlpha(mood.core, 60 * pulse), Color.TRANSPARENT),
            floatArrayOf(0.3f, 0.65f, 1f),
            Shader.TileMode.CLAMP,
        )
        canvas.drawCircle(cx, cy, haloR, halo)

        body.shader = RadialGradient(
            cx - r * 0.3f, cy - r * 0.35f, r * 1.4f,
            intArrayOf(mood.glow, mood.core, darken(mood.core)),
            floatArrayOf(0f, 0.55f, 1f),
            Shader.TileMode.CLAMP,
        )
        canvas.drawCircle(cx, cy, r, body)
        canvas.drawCircle(cx - r * 0.32f, cy - r * 0.38f, r * 0.26f, shine)

        if (mood == Mood.THINKING) {
            val rr = r * 1.28f
            ring.strokeWidth = r * 0.14f
            ring.color = mood.glow
            canvas.drawArc(cx - rr, cy - rr, cx + rr, cy + rr, phase * 720f, 110f, false, ring)
        }
    }

    private fun withAlpha(color: Int, alpha: Float) =
        Color.argb(alpha.toInt().coerceIn(0, 255), Color.red(color), Color.green(color), Color.blue(color))

    private fun darken(color: Int) =
        Color.rgb((Color.red(color) * 0.55f).toInt(), (Color.green(color) * 0.55f).toInt(), (Color.blue(color) * 0.55f).toInt())
}
