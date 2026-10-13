package app.sakura.fishing

import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log

/** Получает разрешение на захват экрана и держит ScreenGrabber. Должен быть foreground-сервисом типа mediaProjection. */
class CaptureService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null || intent.action == ACTION_STOP) {
            shutdown()
            stopSelf()
            return START_NOT_STICKY
        }
        val code = intent.getIntExtra("code", 0)
        @Suppress("DEPRECATION")
        val data: Intent? = if (Build.VERSION.SDK_INT >= 33)
            intent.getParcelableExtra("data", Intent::class.java) else intent.getParcelableExtra("data")
        if (data == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        val n = Notif.build(this, "Вижу экран", false)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(2, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(2, n)
        }
        try {
            shutdown()
            val mpm = getSystemService(MediaProjectionManager::class.java)
            val proj = mpm.getMediaProjection(code, data)
            val g = ScreenGrabber(applicationContext, proj)
            proj.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    Log.i(Bridge.TAG, "projection stopped")
                    if (Bridge.grabber === g) Bridge.grabber = null
                    g.stop()
                    stopSelf()
                }
            }, Handler(Looper.getMainLooper()))
            Bridge.grabber = g
            g.start()
        } catch (t: Throwable) {
            Log.e(Bridge.TAG, "capture start failed: $t")
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun shutdown() {
        val g = Bridge.grabber
        Bridge.grabber = null
        g?.stop()
    }

    override fun onDestroy() {
        shutdown()
        super.onDestroy()
    }

    companion object {
        const val ACTION_STOP = "app.sakura.fishing.STOP_CAPTURE"
    }
}
