package app.fakefish

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.os.SystemClock
import android.util.Log
import android.view.Choreographer
import android.view.MotionEvent
import android.view.View
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.sin
import kotlin.random.Random

/**
 * Подставная «рыбалка» для проверки макроса на настоящем Android.
 * Всё похоже на настоящую игру: кнопка заброса, поклёвка, шкала с шаром (держишь палец — шар вверх),
 * потом висит рыба с белой кнопкой «Collect», её надо держать ~2.2 с; кнопка иногда прыгает и исчезает.
 */
class GameView(ctx: Context) : View(ctx), Choreographer.FrameCallback {
    private enum class St { IDLE, LINE, GAME, FISH }

    private val rnd = Random(7)
    private var st = St.IDLE
    private var tState = 0.0
    private var biteAt = 0.0
    private var rodOn = true

    // миниигра
    private var ballY = 0.0
    private var ballV = 0.0
    private var progress = 0.0
    private var tGame = 0.0
    private var inZoneT = 0.0

    // сбор
    private var fx = 0f
    private var fy = 0f
    private var fishVisible = true
    private var nextJump = 0.0
    private var hideUntil = 0.0
    private var holdIn = 0.0
    private var fishAge = 0.0

    // касания
    private var held = false
    private var downAt = 0L
    private var touchX = 0f
    private var touchY = 0f
    private var downs = 0
    private var gameDowns = 0
    private var gameHeldMs = 0.0
    private var prevHeld = false

    // счётчики
    private var casts = 0
    private var catches = 0
    private var fails = 0
    private var collects = 0
    private var missed = 0
    private var breaks = 0
    private var tapsFish = 0
    private var lastStat = 0.0

    private var tNow = 0.0
    private var lastFrame = 0L
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)

    private val inst = ++instances
    private var alive = true
    private var frameNo = 0

    init {
        isFocusable = true
        Choreographer.getInstance().postFrameCallback(this)
        Log.i(TAG, "START inst=$inst")
    }

    override fun onDetachedFromWindow() {
        alive = false
        Choreographer.getInstance().removeFrameCallback(this)
        Log.i(TAG, "DETACH inst=$inst")
        super.onDetachedFromWindow()
    }

    // ---------- раскладка (доли экрана, как в настоящей игре на телефоне)
    private fun W() = width.toFloat()
    private fun H() = height.toFloat()
    private fun barX0() = 0.7325f * W()
    private fun barX1() = 0.7675f * W()
    private fun barTop() = 0.157f * H()
    private fun barBot() = 0.69f * H()
    private fun ballH() = 0.042f * H()
    private fun ballW() = 0.017f * W()
    var easy = false      // облегчённый режим для проверки цепочки «поймал -> собрал -> заново»: зона шире и медленнее
    private fun zoneH() = (if (easy) 0.10f else 0.055f) * H()
    private fun castX() = 0.80f * W()
    private fun castY() = 0.33f * H()
    private fun castR() = 0.06f * H()
    private fun rodX() = 0.93f * W()
    private fun rodY() = 0.9f * H()
    private fun rodR() = 0.06f * H()
    private fun iconR() = 0.045f * H()

    private fun zoneC(t: Double): Double {
        val mid = (barTop() + barBot()) / 2.0
        val span = (barBot() - barTop()).toDouble()
        val k = if (easy) 0.6 else 1.0
        return mid + 0.27 * span * sin(0.8 * k * t) + 0.09 * span * sin(2.1 * k * t)
    }

    override fun doFrame(ns: Long) {
        if (!alive) return
        val now = SystemClock.elapsedRealtime()
        val dt = if (lastFrame == 0L) 0.016 else ((now - lastFrame) / 1000.0).coerceAtMost(0.1)
        lastFrame = now
        tNow += dt
        step(dt)
        frameNo++
        if (frameNo % 2 == 0) invalidate()      // рисуем 30 к/с: на CI-эмуляторе каждый процент процессора на счету
        Choreographer.getInstance().postFrameCallback(this)
    }

    private fun step(dt: Double) {
        if (width == 0) return
        tState += dt
        when (st) {
            St.LINE -> if (tState >= biteAt) startGame()
            St.GAME -> stepGame(dt)
            St.FISH -> stepFish(dt)
            St.IDLE -> {}
        }
        if (tNow - lastStat >= 10.0) {
            lastStat = tNow
            Log.i(TAG, "STAT inst=$inst t=${tNow.toInt()} casts=$casts catches=$catches fails=$fails collects=$collects missed=$missed breaks=$breaks tapsFish=$tapsFish downs=$downs gameDowns=$gameDowns")
        }
    }

    private fun enter(s: St) { st = s; tState = 0.0 }

    private fun startGame() {
        enter(St.GAME)
        ballY = (barBot() - ballH() / 2 - 6f).toDouble()
        ballV = 0.0
        progress = 0.0
        tGame = 0.0
        inZoneT = 0.0
        gameDowns = 0
        gameHeldMs = 0.0
        Log.i(TAG, "MG_START")
    }

    private fun stepGame(dt: Double) {
        tGame += dt
        val s = ballH() / 24.0
        val a = 900.0 * s
        ballV += (if (held) -a else a) * dt
        ballY += ballV * dt
        val lo = barTop() + ballH() / 2.0 + 4
        val hi = barBot() - ballH() / 2.0 - 4
        if (ballY < lo) { ballY = lo; ballV = 0.0 }
        if (ballY > hi) { ballY = hi; ballV = 0.0 }
        val zc = zoneC(tGame)
        val inside = abs(ballY - zc) <= zoneH() / 2.0
        if (inside) inZoneT += dt
        progress = (progress + (if (inside) 1.0 else -0.7) * dt).coerceAtLeast(0.0)
        if (held) gameHeldMs += dt * 1000
        if (frameNo % 6 == 0) Log.i(TAG, "TR ${System.currentTimeMillis()} ${ballY.toInt()} ${zc.toInt()} ${if (held) 1 else 0}")
        if (progress >= 3.5) {
            catches++
            Log.i(TAG, "MG_END ok=1 t=${"%.1f".format(tGame)} inzone=${"%.1f".format(inZoneT)} downs=$gameDowns held=${gameHeldMs.toInt()}ms")
            startFish()
        } else if (tGame >= 25.0) {
            fails++
            Log.i(TAG, "MG_END ok=0 t=${"%.1f".format(tGame)} inzone=${"%.1f".format(inZoneT)} downs=$gameDowns held=${gameHeldMs.toInt()}ms")
            enter(St.IDLE)
        }
    }

    private fun startFish() {
        enter(St.FISH)
        fx = (0.30f + rnd.nextFloat() * 0.2f) * W()
        fy = (0.40f + rnd.nextFloat() * 0.15f) * H()
        fishVisible = true
        nextJump = tNow + 3.0 + rnd.nextDouble() * 3.0
        hideUntil = 0.0
        holdIn = 0.0
        fishAge = 0.0
        Log.i(TAG, "FISH x=${fx.toInt()} y=${fy.toInt()}")
    }

    private fun stepFish(dt: Double) {
        fishAge += dt
        if (fishVisible && tNow >= nextJump) {
            // рыба качнулась: кнопка уезжает и на время пропадает
            fx = (0.25f + rnd.nextFloat() * 0.3f) * W()
            fy = (0.35f + rnd.nextFloat() * 0.25f) * H()
            fishVisible = false
            hideUntil = tNow + 0.5 + rnd.nextDouble() * 0.5
            if (holdIn > 0.3) { breaks++; Log.i(TAG, "COLLECT_BREAK hold=${"%.1f".format(holdIn)}") }
            holdIn = 0.0
        }
        if (!fishVisible && tNow >= hideUntil) {
            fishVisible = true
            nextJump = tNow + 3.0 + rnd.nextDouble() * 3.0
        }
        val on = fishVisible && held && hypot((touchX - fx).toDouble(), (touchY - fy).toDouble()) <= iconR() * 1.5
        if (on) {
            holdIn += dt
            if (holdIn >= 2.2) {
                collects++
                Log.i(TAG, "COLLECT_OK age=${"%.1f".format(fishAge)}")
                enter(St.IDLE)
            }
        } else {
            if (holdIn > 0.3) { breaks++; Log.i(TAG, "COLLECT_BREAK hold=${"%.1f".format(holdIn)}") }
            holdIn = 0.0
        }
        if (st == St.FISH && fishAge > 60.0) {
            missed++
            Log.i(TAG, "FISH_MISSED")
            enter(St.IDLE)
        }
    }

    // ---------- касания
    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                Log.i(TAG, "EV D ${System.currentTimeMillis()}")
                held = true
                downAt = SystemClock.elapsedRealtime()
                touchX = e.x; touchY = e.y
                downs++
                if (st == St.GAME && !prevHeld) gameDowns++
                if (st == St.FISH) tapsFish++
                prevHeld = true
                onPress(e.x, e.y)
            }
            MotionEvent.ACTION_MOVE -> { touchX = e.x; touchY = e.y }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                Log.i(TAG, "EV U ${System.currentTimeMillis()}")
                held = false
                prevHeld = false
            }
        }
        return true
    }

    private fun onPress(x: Float, y: Float) {
        if (hypot((x - rodX()).toDouble(), (y - rodY()).toDouble()) <= rodR()) {
            rodOn = !rodOn
            Log.i(TAG, "ROD on=$rodOn")
            if (!rodOn && st == St.LINE) enter(St.IDLE)
            return
        }
        if (st == St.IDLE && rodOn && hypot((x - castX()).toDouble(), (y - castY()).toDouble()) <= castR()) {
            casts++
            biteAt = 2.0 + rnd.nextDouble() * 4.0
            enter(St.LINE)
            Log.i(TAG, "CAST bite_in=${"%.1f".format(biteAt)}")
        }
    }

    // ---------- рисование
    override fun onDraw(c: Canvas) {
        val w = W(); val h = H()
        // небо/вода
        p.style = Paint.Style.FILL
        p.color = Color.rgb(48, 112, 200); c.drawRect(0f, 0f, w, h * 0.42f, p)
        p.color = Color.rgb(18, 58, 140); c.drawRect(0f, h * 0.42f, w, h, p)
        p.color = Color.argb(70, 200, 225, 255)
        for (i in 0 until 9) {
            val yy = h * (0.46f + i * 0.055f)
            val off = (tNow * (20 + i * 4)).toFloat() % 220f
            var xx = -220f + off
            while (xx < w) { c.drawRoundRect(RectF(xx, yy, xx + 110f, yy + 6f), 3f, 3f, p); xx += 220f }
        }
        if (st == St.LINE || st == St.GAME) {
            p.color = Color.argb(220, 235, 235, 245); p.strokeWidth = 3f
            c.drawLine(w * 0.46f, h * 0.9f, w * 0.43f, h * 0.55f, p)
        }
        if (st == St.GAME) drawBar(c)
        if (st == St.IDLE || st == St.LINE) drawCast(c)
        if (st == St.FISH) drawFish(c)
        if (st != St.GAME) drawRod(c)
        if (st == St.GAME) {
            p.style = Paint.Style.FILL; p.color = Color.rgb(200, 40, 40)
            c.drawRoundRect(RectF(w * 0.405f, h * 0.945f, w * 0.45f, h * 0.99f), 8f, 8f, p)
        }
    }

    private fun drawBar(c: Canvas) {
        val r = RectF(barX0(), barTop(), barX1(), barBot())
        p.style = Paint.Style.FILL; p.color = Color.argb(215, 20, 28, 40)
        c.drawRoundRect(r, 18f, 18f, p)
        p.style = Paint.Style.STROKE; p.strokeWidth = 4f; p.color = Color.argb(230, 190, 215, 245)
        c.drawRoundRect(r, 18f, 18f, p)
        p.strokeWidth = 1.5f; p.color = Color.argb(90, 180, 200, 230)
        var y = barTop() + 12f
        while (y < barBot() - 8f) { c.drawLine(barX0() + 10f, y, barX0() + 26f, y, p); y += 14f }
        // зона
        val zc = zoneC(tGame).toFloat()
        val zr = RectF(barX0() - 2f, zc - zoneH() / 2f, barX1() + 2f, zc + zoneH() / 2f)
        p.style = Paint.Style.FILL; p.color = Color.argb(70, 85, 255, 34); c.drawRoundRect(zr, 6f, 6f, p)
        p.style = Paint.Style.STROKE; p.strokeWidth = 5f; p.color = Color.rgb(102, 255, 51); c.drawRoundRect(zr, 6f, 6f, p)
        // шар
        val cx = (barX0() + barX1()) / 2f
        val br = RectF(cx - ballW() / 2f, (ballY - ballH() / 2).toFloat(), cx + ballW() / 2f, (ballY + ballH() / 2).toFloat())
        p.style = Paint.Style.FILL; p.color = Color.rgb(245, 245, 245); c.drawRoundRect(br, 7f, 7f, p)
        // процент
        p.color = Color.rgb(255, 80, 80); p.textSize = 0.032f * H(); p.typeface = Typeface.DEFAULT_BOLD; p.textAlign = Paint.Align.CENTER
        c.drawText("${(progress / 3.5 * 100).toInt()}%", W() * 0.435f, H() * 0.9f, p)
    }

    private fun hand(c: Canvas, x: Float, y: Float, r: Float, color: Int) {
        p.style = Paint.Style.FILL; p.color = color
        c.drawRoundRect(RectF(x - r * 0.12f, y - r * 0.55f, x + r * 0.12f, y + r * 0.05f), r * 0.1f, r * 0.1f, p)
        c.drawRoundRect(RectF(x - r * 0.34f, y - r * 0.1f, x + r * 0.34f, y + r * 0.5f), r * 0.14f, r * 0.14f, p)
    }

    private fun drawCast(c: Canvas) {
        p.style = Paint.Style.FILL; p.color = Color.argb(200, 12, 12, 16)
        c.drawCircle(castX(), castY(), castR(), p)
        hand(c, castX(), castY(), castR() * 0.8f, Color.WHITE)
    }

    private fun drawRod(c: Canvas) {
        p.style = Paint.Style.FILL; p.color = if (rodOn) Color.argb(220, 60, 160, 90) else Color.argb(160, 90, 90, 100)
        c.drawCircle(rodX(), rodY(), rodR(), p)
        p.style = Paint.Style.STROKE; p.strokeWidth = 4f; p.color = Color.WHITE
        c.drawLine(rodX() - rodR() * 0.5f, rodY() + rodR() * 0.5f, rodX() + rodR() * 0.5f, rodY() - rodR() * 0.5f, p)
    }

    private fun drawFish(c: Canvas) {
        // рыба
        p.style = Paint.Style.FILL; p.color = Color.rgb(235, 150, 40)
        c.drawOval(RectF(fx - 0.04f * W(), fy - 0.045f * H(), fx + 0.07f * W(), fy + 0.07f * H()), p)
        if (!fishVisible) return
        val r = iconR()
        // подпись справа
        val pill = RectF(fx + r * 1.1f, fy - r * 0.9f, fx + r * 1.1f + 0.2f * W(), fy + r * 0.9f)
        p.color = Color.argb(225, 22, 32, 52); c.drawRoundRect(pill, r * 0.9f, r * 0.9f, p)
        p.color = Color.WHITE; p.typeface = Typeface.DEFAULT_BOLD; p.textAlign = Paint.Align.LEFT
        p.textSize = r * 0.8f; c.drawText("Golden Fish", pill.left + r * 0.5f, fy - r * 0.05f, p)
        p.textSize = r * 0.55f; p.color = Color.rgb(200, 210, 230); c.drawText("Collect", pill.left + r * 0.5f, fy + r * 0.6f, p)
        // белая кнопка с рукой: то круг, то ромб
        p.color = Color.WHITE
        val diamond = ((tNow * 1.4).toInt() % 2) == 1
        if (diamond) {
            c.save(); c.rotate(45f, fx, fy)
            c.drawRoundRect(RectF(fx - r * 0.8f, fy - r * 0.8f, fx + r * 0.8f, fy + r * 0.8f), r * 0.2f, r * 0.2f, p); c.restore()
        } else c.drawCircle(fx, fy, r, p)
        hand(c, fx, fy, r * 0.9f, Color.rgb(20, 20, 24))
        if (holdIn > 0) {
            p.style = Paint.Style.STROKE; p.strokeWidth = 6f; p.color = Color.rgb(255, 215, 90)
            c.drawArc(RectF(fx - r * 1.2f, fy - r * 1.2f, fx + r * 1.2f, fy + r * 1.2f), -90f, (holdIn / 2.2 * 360).toFloat(), false, p)
        }
    }

    companion object { const val TAG = "FAKEFISH"; var instances = 0 }
}
