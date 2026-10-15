package app.sakura.fishing

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.accessibilityservice.GestureDescription.StrokeDescription
import android.content.Intent
import android.graphics.Color
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.TimeUnit

/**
 * Руки макроса: тапы и удержание пальца, а ещё глаза на «какое приложение сейчас на экране».
 * Заодно рисует маленькую кнопку-сакуру поверх игры (старт/стоп) и умеет выбрать точку на экране.
 */
class MacroAccess : AccessibilityService() {
    private val ui = Handler(Looper.getMainLooper())
    private val gThread = HandlerThread("sakura-gesture").also { it.start() }
    private val gHandler = Handler(gThread.looper)
    private lateinit var wm: WindowManager

    private var chip: TextView? = null
    private var banner: View? = null
    private var shade: View? = null

    @Volatile private var lastPkg = ""
    val gSent = AtomicInteger()
    val gDone = AtomicInteger()
    val gCancel = AtomicInteger()
    val gFail = AtomicInteger()
    private var polling = true

    // ---------- состояние удержания пальца (порт Touch из исходного макроса)
    private val tl = Any()
    @Volatile private var tDown = false
    @Volatile private var tBroken = false
    @Volatile private var tStroke: StrokeDescription? = null
    @Volatile private var tPending: CountDownLatch? = null
    @Volatile private var tLastSent = 0L
    private var lx = 0f
    private var ly = 0f
    private var hx = 0f
    private var hy = 0f
    /** 0 — как в исходном макросе (палец «открыт» и живёт между жестами); 1 — длинные отдельные касания, отпускание «перебивает» их. */
    @Volatile var holdMethod = 0
    private var longOn = false
    private var longGen = 0
    private val kThread = HandlerThread("sakura-keepalive").also { it.start() }
    private val kHandler = Handler(kThread.looper)

    override fun onServiceConnected() {
        super.onServiceConnected()
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        Bridge.access = this
        Bridge.appCtx = applicationContext
        // Ядро (Python) должно жить, пока включена служба.
        try {
            startForegroundService(Intent(this, CoreService::class.java))
        } catch (t: Throwable) {
            Log.w(Bridge.TAG, "core start: $t")
        }
        ui.post { addChip() }
        kHandler.removeCallbacks(keepRun)
        kHandler.postDelayed(keepRun, 250)
        startPolling()
    }

    override fun onAccessibilityEvent(e: AccessibilityEvent?) {
        val p = e?.packageName?.toString() ?: return
        if (e.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            if (p != "android" && !p.startsWith("com.android.systemui") && !p.contains("inputmethod") && p != packageName) {
                lastPkg = p
            } else if (p == packageName) {
                lastPkg = p
            }
        }
    }

    override fun onInterrupt() { releaseAll() }

    override fun onDestroy() {
        kHandler.removeCallbacks(keepRun)
        polling = false
        releaseAll()
        ui.post { removeChip(); removePick() }
        if (Bridge.access === this) Bridge.access = null
        gThread.quitSafely()
        aThread.quitSafely()
        kThread.quitSafely()
        super.onDestroy()
    }

    fun foregroundPkg(): String {
        val r = try { rootInActiveWindow?.packageName?.toString() } catch (t: Throwable) { null }
        if (!r.isNullOrEmpty() && !r.contains("inputmethod")) return r
        return lastPkg
    }

    fun toast(msg: String) {
        ui.post { Toast.makeText(applicationContext, msg, Toast.LENGTH_LONG).show() }
    }

    // ---------- жесты
    private fun pathAt(x: Float, y: Float): Path = Path().apply { moveTo(x, y) }

    private fun waitPending(ms: Long) {
        val l = tPending ?: return
        try { l.await(ms, TimeUnit.MILLISECONDS) } catch (e: InterruptedException) { Thread.currentThread().interrupt() }
    }

    /** Отправляет жест; перед этим дожидается конца предыдущего (иначе он его отменит). */
    private fun tSend(st: StrokeDescription, waitMs: Long): Boolean {
        waitPending(300)
        val latch = CountDownLatch(1)
        val done = java.util.concurrent.atomic.AtomicBoolean(false)
        tPending = latch
        gSent.incrementAndGet()
        val ok = try {
            dispatchGesture(GestureDescription.Builder().addStroke(st).build(), object : GestureResultCallback() {
                override fun onCompleted(d: GestureDescription?) { gDone.incrementAndGet(); done.set(true); latch.countDown() }
                override fun onCancelled(d: GestureDescription?) {
                    gCancel.incrementAndGet()
                    if (tStroke === st && tDown) tBroken = true
                    latch.countDown()
                }
            }, gHandler)
        } catch (t: Throwable) { false }
        if (!ok) { gFail.incrementAndGet(); latch.countDown(); return false }
        tLastSent = System.currentTimeMillis()
        if (waitMs <= 0) return true
        try { latch.await(waitMs, TimeUnit.MILLISECONDS) } catch (e: InterruptedException) { Thread.currentThread().interrupt() }
        return done.get()
    }

    private fun tBegin(x: Float, y: Float) {
        if (tDown && !tBroken && x == lx && y == ly) return
        if (tDown) tEnd()
        tBroken = false
        val st = StrokeDescription(pathAt(x, y), 0L, SEG_MS, true)
        tStroke = st; tDown = true; lx = x; ly = y
        tSend(st, 0L)
    }

    private fun tMoveTo(x: Float, y: Float, ms: Long) {
        val prev = tStroke
        if (!tDown || tBroken || prev == null) { tBegin(x, y); return }
        val st = prev.continueStroke(pathAt(x, y), 0L, Math.max(1L, ms), true)
        tStroke = st; lx = x; ly = y
        tSend(st, 0L)
    }

    private fun tEnd() {
        if (!tDown) return
        tDown = false
        val st = tStroke
        tStroke = null
        if (st == null || tBroken) { tBroken = false; return }
        tSend(st.continueStroke(pathAt(lx, ly), 0L, 1L, false), 0L)
    }

    private fun tKeepAlive() {
        if (tDown && !tBroken && System.currentTimeMillis() - tLastSent >= KEEP_ALIVE_MS) {
            waitPending(100)
            tMoveTo(lx, ly, SEG_MS)
        }
    }

    private val keepRun = object : Runnable {
        override fun run() {
            try { synchronized(tl) { tKeepAlive() } } catch (t: Throwable) { /* ignore */ }
            kHandler.postDelayed(this, 250)
        }
    }

    /** Короткий тап, блокирует вызывающий поток до конца жеста. */
    fun tap(x: Float, y: Float, ms: Long): Boolean {
        val dur = Math.max(1L, Math.min(1500L, ms))
        wantDown = false
        return synchronized(tl) {
            tEnd()
            tSend(StrokeDescription(pathAt(x, y), 0L, dur), dur + 1500)
        }
    }

    /** Одно длинное касание ровно на ms (как «Hold» для сбора). Блокирует. */
    fun holdFor(x: Float, y: Float, ms: Long): Boolean {
        wantDown = false
        return synchronized(tl) {
            tEnd()
            waitPending(400)
            tSend(StrokeDescription(pathAt(x, y), 0L, Math.max(1L, Math.min(MAX_STROKE_MS, ms))), ms + 2000)
        }
    }

    @Volatile private var asyncUntil = 0L

    /** Одно длинное касание на ms, НЕ блокирует. Без «продолжений»: система не обрывает его на полпути. */
    fun holdAsync(x: Float, y: Float, ms: Long): Boolean {
        wantDown = false
        return synchronized(tl) {
            tEnd()
            waitPending(400)
            val dur = Math.max(1L, Math.min(MAX_STROKE_MS, ms))
            asyncUntil = System.currentTimeMillis() + dur
            tSend(StrokeDescription(pathAt(x, y), 0L, dur), 0L)
        }
    }

    /** Поднять палец, если длинное касание ещё идёт (новый жест отменяет прежний; тап — у левого края). */
    fun cancelHold() {
        if (System.currentTimeMillis() >= asyncUntil) return
        asyncUntil = 0L
        synchronized(tl) {
            val sz = Bridge.realSize(this)
            val g = GestureDescription.Builder()
                .addStroke(StrokeDescription(pathAt(sz[0] * 0.012f, sz[1] * 0.5f), 0, 8L)).build()
            gSent.incrementAndGet()
            val ok = try { dispatchGesture(g, null, gHandler) } catch (t: Throwable) { false }
            if (!ok) gFail.incrementAndGet()
        }
    }

    // «хочу» — что просит питон; применяет отдельный поток, так что питон не ждёт системы. Побеждает последнее пожелание.
    @Volatile private var wantDown = false
    @Volatile private var wantX = 0f
    @Volatile private var wantY = 0f
    private val applying = java.util.concurrent.atomic.AtomicBoolean(false)
    private val aThread = HandlerThread("sakura-apply").also { it.start() }
    private val aHandler = Handler(aThread.looper)

    private val applyRun = Runnable {
        while (true) {
            try {
                while (true) {
                    val d = wantDown; val x = wantX; val y = wantY
                    synchronized(tl) {
                        if (d) {
                            if (tDown && !tBroken && x == lx && y == ly) tKeepAlive()
                            tBegin(x, y)
                        } else tEnd()
                    }
                    if (d == wantDown && x == wantX && y == wantY) break
                }
            } catch (t: Throwable) {
                Log.w(Bridge.TAG, "apply: $t")
            }
            applying.set(false)
            // могли прийти новые пожелания, пока мы выходили
            val needMore = (wantDown != tDown) || (wantDown && (wantX != lx || wantY != ly))
            if (!needMore || !applying.compareAndSet(false, true)) break
        }
    }

    /** Нажать и держать (down=true) или отпустить (false). Не блокирует. */
    fun setHold(x: Float, y: Float, down: Boolean) {
        if (holdMethod == 1) { longHold(x, y, down); return }
        wantX = x; wantY = y; wantDown = down
        if (applying.compareAndSet(false, true)) aHandler.post(applyRun)
    }

    private fun longHold(x: Float, y: Float, down: Boolean) {
        synchronized(tl) {
            if (down) {
                if (longOn) return
                longOn = true; hx = x; hy = y
                longGen++
                dispatchLong(longGen)
            } else {
                if (!longOn) return
                longOn = false
                longGen++
                // новый жест отменяет прежний — палец поднимается; тап уходит в безопасное место у левого края
                val sz = Bridge.realSize(this)
                val g = GestureDescription.Builder()
                    .addStroke(StrokeDescription(pathAt(sz[0] * 0.012f, sz[1] * 0.5f), 0, 8L)).build()
                gSent.incrementAndGet()
                val ok = try { dispatchGesture(g, null, gHandler) } catch (t: Throwable) { false }
                if (!ok) gFail.incrementAndGet()
            }
        }
    }

    private fun dispatchLong(gen: Int) {
        val g = GestureDescription.Builder().addStroke(StrokeDescription(pathAt(hx, hy), 0, LONG_MS)).build()
        gSent.incrementAndGet()
        val ok = try {
            dispatchGesture(g, object : GestureResultCallback() {
                override fun onCompleted(d: GestureDescription?) {
                    gDone.incrementAndGet()
                    synchronized(tl) { if (longOn && gen == longGen) { longGen++; dispatchLong(longGen) } }
                }
                override fun onCancelled(d: GestureDescription?) {
                    gCancel.incrementAndGet()
                    synchronized(tl) { if (longOn && gen == longGen) { longGen++; dispatchLong(longGen) } }
                }
            }, gHandler)
        } catch (t: Throwable) { false }
        if (!ok) { gFail.incrementAndGet(); longOn = false }
    }

    fun releaseAll() {
        wantDown = false
        cancelHold()
        if (longOn) longHold(hx, hy, false)
        synchronized(tl) { tEnd() }
        waitPending(400)
    }

    // ---------- кнопка-сакура поверх игры
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun addChip() {
        if (chip != null) return
        val tv = TextView(this).apply {
            text = "🌸"
            textSize = 22f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(0xCCD6366F.toInt())
                setStroke(dp(2), Color.WHITE)
            }
        }
        val lp = WindowManager.LayoutParams(
            dp(46), dp(46), WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 0
            y = Bridge.realSize(this@MacroAccess)[1] / 3
        }
        var sx = 0f; var sy = 0f; var ox = 0; var oy = 0; var moved = false
        tv.setOnTouchListener { _, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> { sx = e.rawX; sy = e.rawY; ox = lp.x; oy = lp.y; moved = false }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - sx; val dy = e.rawY - sy
                    if (Math.abs(dx) > dp(8) || Math.abs(dy) > dp(8)) moved = true
                    if (moved) {
                        lp.x = ox + dx.toInt(); lp.y = oy + dy.toInt()
                        try { wm.updateViewLayout(tv, lp) } catch (t: Throwable) { /* ignore */ }
                    }
                }
                MotionEvent.ACTION_UP -> if (!moved) onChipTap()
            }
            true
        }
        try {
            wm.addView(tv, lp)
            chip = tv
        } catch (t: Throwable) {
            Log.w(Bridge.TAG, "chip: $t")
        }
    }

    private fun removeChip() {
        chip?.let { try { wm.removeView(it) } catch (t: Throwable) { /* ignore */ } }
        chip = null
    }

    private fun onChipTap() {
        Bridge.pyAsync("toggle") { msg ->
            if (!msg.isNullOrEmpty() && msg != "None") {
                toast(msg)
                // не готова — покажем панель
                ui.post {
                    startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
            }
        }
    }

    private fun startPolling() {
        Thread {
            while (polling) {
                try {
                    val r = Bridge.py("is_running")
                    val on = r == "True"
                    ui.post { chip?.text = if (on) "⏹" else "🌸" }
                } catch (t: Throwable) { /* ignore */ }
                try { Thread.sleep(1000) } catch (t: InterruptedException) { return@Thread }
            }
        }.start()
    }

    // ---------- выбор точки на экране
    fun startPick(name: String) {
        ui.post {
            removePick()
            val label = when (name) {
                "cast" -> "точку заброса (куда тапаешь, чтобы забросить)"
                "collect" -> "кнопку «Собрать»"
                else -> "слот удочки на панели"
            }
            val bar = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(14), dp(8), dp(8), dp(8))
                background = GradientDrawable().apply {
                    cornerRadius = dp(18).toFloat()
                    setColor(0xEE14102B.toInt())
                    setStroke(dp(2), 0xFFFF7EB6.toInt())
                }
            }
            val tv = TextView(this).apply {
                text = "Дойди до места, где видно $label, потом жми →"
                setTextColor(Color.WHITE)
                textSize = 13f
                maxWidth = dp(300)
            }
            val go = TextView(this).apply {
                text = "Выбрать"
                setTextColor(0xFF14102B.toInt())
                textSize = 14f
                setPadding(dp(14), dp(8), dp(14), dp(8))
                background = GradientDrawable().apply { cornerRadius = dp(14).toFloat(); setColor(0xFFFFD36E.toInt()) }
                setOnClickListener { showShade(name) }
            }
            val no = TextView(this).apply {
                text = "✕"
                setTextColor(Color.WHITE)
                textSize = 18f
                setPadding(dp(12), dp(4), dp(8), dp(4))
                setOnClickListener { removePick() }
            }
            bar.addView(tv); bar.addView(go, LinearLayout.LayoutParams(-2, -2).apply { leftMargin = dp(10) }); bar.addView(no)
            val lp = WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT
            ).apply { gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL; y = dp(10) }
            try {
                wm.addView(bar, lp)
                banner = bar
            } catch (t: Throwable) {
                Log.w(Bridge.TAG, "banner: $t")
            }
            Bridge.launchGame()
        }
    }

    private fun showShade(name: String) {
        shade?.let { try { wm.removeView(it) } catch (t: Throwable) { /* ignore */ } }
        val v = FrameLayout(this)
        v.setBackgroundColor(0x66000000)
        val hint = TextView(this).apply {
            text = "Тапни ровно по нужному месту"
            setTextColor(Color.WHITE)
            textSize = 20f
            gravity = Gravity.CENTER
        }
        v.addView(hint, FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))
        v.setOnTouchListener { _, e ->
            if (e.actionMasked == MotionEvent.ACTION_UP) {
                val d = Bridge.realSize(this)
                val fx = (e.rawX / d[0]).toDouble()
                val fy = (e.rawY / d[1]).toDouble()
                removePick()
                Bridge.pyAsync("point_picked", name, fx, fy)
                toast("Точка сохранена ✓")
                ui.postDelayed({
                    try {
                        startActivity(Intent(this, MainActivity::class.java)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
                    } catch (t: Throwable) { /* ignore */ }
                }, 400)
            }
            true
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        )
        try {
            wm.addView(v, lp)
            shade = v
        } catch (t: Throwable) {
            Log.w(Bridge.TAG, "shade: $t")
        }
    }

    private fun removePick() {
        banner?.let { try { wm.removeView(it) } catch (t: Throwable) { /* ignore */ } }
        shade?.let { try { wm.removeView(it) } catch (t: Throwable) { /* ignore */ } }
        banner = null
        shade = null
    }

    companion object {
        const val SEG_MS = 10L
        const val KEEP_ALIVE_MS = 1000L
        const val MAX_STROKE_MS = 59000L
        const val LONG_MS = 350L
    }
}
