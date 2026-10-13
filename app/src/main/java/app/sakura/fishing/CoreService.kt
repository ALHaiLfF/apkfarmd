package app.sakura.fishing

import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/** Хозяин Python: поднимает мозг и веб-панель, живёт в фоне. */
class CoreService : Service() {
    private var wake: PowerManager.WakeLock? = null
    private var booting = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Bridge.appCtx = applicationContext
        val n = Notif.build(this, "Готова рыбачить", true)
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, n)
        }
        val pm = getSystemService(PowerManager::class.java)
        wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "sakura:core").also { it.acquire() }
        boot()
    }

    private fun boot() {
        if (booting || Bridge.panelUrl.isNotEmpty()) return
        booting = true
        Thread {
            try {
                if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                val mod = Python.getInstance().getModule("glue")
                mod.callAttr("boot", filesDir.absolutePath)
                Bridge.panelUrl = mod.callAttr("url").toString()
                Log.i(Bridge.TAG, "panel at ${Bridge.panelUrl}")
            } catch (t: Throwable) {
                Bridge.bootError = Log.getStackTraceString(t)
                Log.e(Bridge.TAG, "boot failed: $t")
            } finally {
                booting = false
            }
        }.start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_TOGGLE) {
            Bridge.pyAsync("toggle") { msg ->
                if (!msg.isNullOrEmpty() && msg != "None") Bridge.access?.toast(msg)
            }
        }
        if (Bridge.panelUrl.isEmpty() && Bridge.bootError.isNotEmpty()) {
            Bridge.bootError = ""
            boot()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        try { Bridge.py("stop") } catch (t: Throwable) { /* ignore */ }
        try { wake?.release() } catch (t: Throwable) { /* ignore */ }
        super.onDestroy()
    }

    companion object {
        const val ACTION_TOGGLE = "app.sakura.fishing.TOGGLE"
    }
}
