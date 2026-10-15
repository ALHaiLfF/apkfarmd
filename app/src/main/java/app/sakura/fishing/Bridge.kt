package app.sakura.fishing

import android.content.Context
import android.content.Intent
import android.hardware.display.DisplayManager
import android.util.DisplayMetrics
import android.util.Log
import android.view.Display
import com.chaquo.python.Python
import org.json.JSONObject

/** Всё, что вызывает Python (через Chaquopy). Только статические методы. */
object Bridge {
    const val TAG = "Sakura"

    @Volatile @JvmField var appCtx: Context? = null
    @Volatile @JvmField var access: MacroAccess? = null
    @Volatile @JvmField var grabber: ScreenGrabber? = null
    @Volatile @JvmField var panelUrl: String = ""
    @Volatile @JvmField var bootError: String = ""
    @Volatile @JvmField var lastPkg: String = ""

    fun realSize(ctx: Context?): IntArray {
        val c = ctx ?: return intArrayOf(0, 0)
        val dm = DisplayMetrics()
        val d = (c.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager).getDisplay(Display.DEFAULT_DISPLAY)
        @Suppress("DEPRECATION")
        d.getRealMetrics(dm)
        return intArrayOf(dm.widthPixels, dm.heightPixels)
    }

    @JvmStatic fun status(): String {
        val o = JSONObject()
        o.put("access", access != null)
        o.put("capture", grabber?.ready() == true)
        o.put("pkg", foregroundPkg())
        o.put("hm", access?.holdMethod ?: -1)
        val s = screenSize()
        o.put("w", s[0]); o.put("h", s[1])
        val a = access
        o.put("g", if (a == null) "-" else "${a.gSent.get()}/${a.gDone.get()}/${a.gCancel.get()}/${a.gFail.get()}")
        val gr = grabber
        o.put("frames", gr?.frames ?: 0L)
        o.put("age", if (gr != null && gr.stamp > 0) android.os.SystemClock.elapsedRealtime() - gr.stamp else -1L)
        return o.toString()
    }

    @JvmStatic fun frameAge(): Int = (grabber?.contentAgeMs() ?: -1L).toInt()

    @JvmStatic fun captureReady(): Boolean = grabber?.ready() == true

    /** Размер кадра захвата. */
    @JvmStatic fun screenSize(): IntArray {
        val g = grabber
        return if (g != null && g.ready()) intArrayOf(g.w, g.h) else intArrayOf(0, 0)
    }

    /** Размер экрана для касаний (должен совпадать с кадром). */
    @JvmStatic fun displaySize(): IntArray {
        val s = realSize(appCtx)
        return if (s[0] > 0) s else screenSize()
    }

    @JvmStatic fun grab(x: Int, y: Int, w: Int, h: Int): ByteArray? = grabber?.grab(x, y, w, h)
    @JvmStatic fun thumb(w: Int, h: Int): ByteArray? = grabber?.thumbGray(w, h)
    @JvmStatic fun scaled(w: Int, h: Int): ByteArray? = grabber?.scaled(w, h)

    @JvmStatic fun tap(x: Int, y: Int, ms: Int): Boolean = access?.tap(x.toFloat(), y.toFloat(), ms.toLong()) ?: false
    @JvmStatic fun hold(x: Int, y: Int, down: Boolean) { access?.setHold(x.toFloat(), y.toFloat(), down) }
    @JvmStatic fun holdFor(x: Int, y: Int, ms: Int): Boolean = access?.holdFor(x.toFloat(), y.toFloat(), ms.toLong()) ?: false
    @JvmStatic fun holdAsync(x: Int, y: Int, ms: Int): Boolean = access?.holdAsync(x.toFloat(), y.toFloat(), ms.toLong()) ?: false
    @JvmStatic fun cancelHold() { access?.cancelHold() }
    @JvmStatic fun releaseAll() { access?.releaseAll() }
    @JvmStatic fun holdMethod(m: Int) { access?.let { it.releaseAll(); it.holdMethod = m } }

    @JvmStatic fun foregroundPkg(): String = access?.foregroundPkg() ?: ""

    @JvmStatic fun launchGame(): Boolean = launchGame("roblox")

    @JvmStatic fun launchGame(needle: String): Boolean {
        val ctx: Context = access ?: appCtx ?: return false
        return try {
            val pm = ctx.packageManager
            val q = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            val hit = pm.queryIntentActivities(q, 0)
                .firstOrNull { it.activityInfo.packageName.contains(needle, ignoreCase = true) }
                ?: return false
            val li = pm.getLaunchIntentForPackage(hit.activityInfo.packageName) ?: return false
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
            ctx.startActivity(li)
            true
        } catch (t: Throwable) {
            Log.w(TAG, "launchGame: $t")
            false
        }
    }

    /** Сохраняет текущий кадр захвата в Pictures/Rybachka (галерея). */
    @JvmStatic fun saveFrame(tag: String): Boolean {
        return try {
            val ctx = appCtx ?: return false
            val bmp = grabber?.snapshot() ?: return false
            val name = "rybachka_${tag}_${System.currentTimeMillis() / 1000}.png"
            if (android.os.Build.VERSION.SDK_INT >= 29) {
                val cv = android.content.ContentValues().apply {
                    put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name)
                    put(android.provider.MediaStore.Images.Media.MIME_TYPE, "image/png")
                    put(android.provider.MediaStore.Images.Media.RELATIVE_PATH, "Pictures/Rybachka")
                }
                val uri = ctx.contentResolver.insert(android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv) ?: return false
                ctx.contentResolver.openOutputStream(uri)?.use { bmp.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
            } else {
                val dir = ctx.getExternalFilesDir("frames") ?: return false
                java.io.File(dir, name).outputStream().use { bmp.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
            }
            true
        } catch (t: Throwable) {
            Log.w(TAG, "saveFrame: $t")
            false
        }
    }

    /** Вызов функции модуля glue.py из Kotlin. Блокирует вызывающий поток — не звать из UI. */
    fun py(fn: String, vararg args: Any?): String? {
        return try {
            Python.getInstance().getModule("glue").callAttr(fn, *args)?.toString()
        } catch (t: Throwable) {
            Log.w(TAG, "py $fn: $t")
            null
        }
    }

    fun pyAsync(fn: String, vararg args: Any?, done: ((String?) -> Unit)? = null) {
        Thread { val r = py(fn, *args); done?.invoke(r) }.start()
    }
}
