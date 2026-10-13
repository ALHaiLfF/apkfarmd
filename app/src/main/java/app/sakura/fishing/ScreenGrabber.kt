package app.sakura.fishing

import android.content.Context
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Log

/** Держит последний кадр экрана и отдаёт из него куски. Кадр не копируется, пока его не попросят. */
class ScreenGrabber(private val ctx: Context, private val projection: MediaProjection) {
    private val lock = Any()
    private val thread = HandlerThread("sakura-grab").also { it.start() }
    private val handler = Handler(thread.looper)
    private var reader: ImageReader? = null
    private var vd: VirtualDisplay? = null
    private var img: Image? = null
    private val dpi = ctx.resources.displayMetrics.densityDpi

    @Volatile var w = 0
    @Volatile var h = 0
    @Volatile var stamp = 0L
    @Volatile var alive = true

    private val watch = object : Runnable {
        override fun run() {
            if (!alive) return
            try { configure() } catch (t: Throwable) { Log.w(Bridge.TAG, "configure: $t") }
            handler.postDelayed(this, 700)
        }
    }

    fun start() {
        handler.post(watch)
    }

    fun ready(): Boolean = alive && w > 0 && synchronized(lock) { img != null }

    private fun configure() {
        val s = Bridge.realSize(ctx)
        val nw = s[0]
        val nh = s[1]
        if (nw <= 0 || nh <= 0) return
        if (nw == w && nh == h && vd != null) return
        val nr = ImageReader.newInstance(nw, nh, PixelFormat.RGBA_8888, 3)
        nr.setOnImageAvailableListener({ rd ->
            val n = try { rd.acquireLatestImage() } catch (t: Throwable) { null }
            if (n != null) {
                synchronized(lock) {
                    img?.close()
                    img = n
                    stamp = SystemClock.elapsedRealtime()
                }
            }
        }, handler)
        val old = reader
        if (vd == null) {
            vd = projection.createVirtualDisplay(
                "sakura", nw, nh, dpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                nr.surface, null, handler
            )
        } else {
            vd?.resize(nw, nh, dpi)
            vd?.surface = nr.surface
        }
        synchronized(lock) {
            img?.close()
            img = null
            reader = nr
            w = nw
            h = nh
        }
        try { old?.close() } catch (t: Throwable) { /* ignore */ }
    }

    /** RGBA-байты прямоугольника (0..w, 0..h пиксели кадра). */
    fun grab(x: Int, y: Int, cw: Int, ch: Int): ByteArray? {
        synchronized(lock) {
            val im = img ?: return null
            if (cw <= 0 || ch <= 0 || x < 0 || y < 0 || x + cw > im.width || y + ch > im.height) return null
            val plane = im.planes[0]
            val buf = plane.buffer.duplicate()
            val rs = plane.rowStride
            val ps = plane.pixelStride
            val out = ByteArray(cw * ch * 4)
            if (ps == 4) {
                for (r in 0 until ch) {
                    buf.position((y + r) * rs + x * 4)
                    buf.get(out, r * cw * 4, cw * 4)
                }
            } else {
                for (r in 0 until ch) for (c in 0 until cw) {
                    val p = (y + r) * rs + (x + c) * ps
                    val o = (r * cw + c) * 4
                    out[o] = buf.get(p); out[o + 1] = buf.get(p + 1); out[o + 2] = buf.get(p + 2); out[o + 3] = buf.get(p + 3)
                }
            }
            return out
        }
    }

    /** Уменьшенная копия всего кадра (ближайший сосед) в RGBA. */
    fun scaled(tw: Int, th: Int): ByteArray? {
        synchronized(lock) {
            val im = img ?: return null
            if (tw <= 0 || th <= 0) return null
            val plane = im.planes[0]
            val buf = plane.buffer.duplicate()
            val rs = plane.rowStride
            val ps = plane.pixelStride
            val out = ByteArray(tw * th * 4)
            for (ty in 0 until th) {
                val sy = minOf(im.height - 1, ty * im.height / th)
                for (tx in 0 until tw) {
                    val sx = minOf(im.width - 1, tx * im.width / tw)
                    val p = sy * rs + sx * ps
                    val o = (ty * tw + tx) * 4
                    out[o] = buf.get(p); out[o + 1] = buf.get(p + 1); out[o + 2] = buf.get(p + 2); out[o + 3] = buf.get(p + 3)
                }
            }
            return out
        }
    }

    /** Маленькая серая копия для определения «картинка зависла». */
    fun thumbGray(tw: Int, th: Int): ByteArray? {
        synchronized(lock) {
            val im = img ?: return null
            val plane = im.planes[0]
            val buf = plane.buffer.duplicate()
            val rs = plane.rowStride
            val ps = plane.pixelStride
            val out = ByteArray(tw * th)
            for (ty in 0 until th) {
                val sy = minOf(im.height - 1, ty * im.height / th)
                for (tx in 0 until tw) {
                    val sx = minOf(im.width - 1, tx * im.width / tw)
                    val p = sy * rs + sx * ps
                    val r = buf.get(p).toInt() and 0xFF
                    val g = buf.get(p + 1).toInt() and 0xFF
                    val b = buf.get(p + 2).toInt() and 0xFF
                    out[ty * tw + tx] = ((r * 30 + g * 59 + b * 11) / 100).toByte()
                }
            }
            return out
        }
    }

    fun stop() {
        alive = false
        handler.removeCallbacksAndMessages(null)
        synchronized(lock) {
            try { img?.close() } catch (t: Throwable) { /* ignore */ }
            img = null
        }
        try { vd?.release() } catch (t: Throwable) { /* ignore */ }
        vd = null
        try { reader?.close() } catch (t: Throwable) { /* ignore */ }
        reader = null
        try { projection.stop() } catch (t: Throwable) { /* ignore */ }
        thread.quitSafely()
    }
}
