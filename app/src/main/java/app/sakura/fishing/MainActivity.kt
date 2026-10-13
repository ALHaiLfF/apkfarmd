package app.sakura.fishing

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private var web: WebView? = null
    private lateinit var root: FrameLayout
    private lateinit var info: TextView
    private val ui = Handler(Looper.getMainLooper())
    private var loaded = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Bridge.appCtx = applicationContext
        root = FrameLayout(this)
        root.setBackgroundColor(0xFF14102B.toInt())
        info = TextView(this).apply {
            text = "Рыбачка просыпается…"
            setTextColor(Color.WHITE)
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(48, 48, 48, 48)
        }
        root.addView(info, FrameLayout.LayoutParams(-1, -1))
        setContentView(root)

        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 7)
        }
        startForegroundService(Intent(this, CoreService::class.java))
        waitForPanel()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun showPanel(url: String) {
        if (loaded) return
        loaded = true
        val w = WebView(this)
        w.setBackgroundColor(0xFF14102B.toInt())
        w.settings.javaScriptEnabled = true
        w.settings.domStorageEnabled = true
        w.webViewClient = WebViewClient()
        w.addJavascriptInterface(Js(), "Android")
        root.removeAllViews()
        root.addView(w, ViewGroup.LayoutParams(-1, -1))
        web = w
        w.loadUrl(url)
    }

    private fun waitForPanel() {
        Thread {
            var waited = 0
            while (!isFinishing) {
                val url = Bridge.panelUrl
                if (url.isNotEmpty()) {
                    ui.post { showPanel(url) }
                    return@Thread
                }
                if (Bridge.bootError.isNotEmpty()) {
                    val err = Bridge.bootError
                    ui.post { showError(err) }
                    return@Thread
                }
                try { Thread.sleep(200) } catch (t: InterruptedException) { return@Thread }
                waited += 200
                if (waited == 20000) ui.post { info.text = "Всё ещё запускаюсь… (первый запуск может занять до минуты)" }
            }
        }.start()
    }

    private fun showError(err: String) {
        val sv = ScrollView(this)
        val tv = TextView(this).apply {
            text = "Не получилось запуститься. Перешли этот текст разработчику:\n\n$err"
            setTextColor(Color.WHITE)
            textSize = 12f
            setTextIsSelectable(true)
            setPadding(32, 48, 32, 48)
        }
        sv.addView(tv)
        root.removeAllViews()
        root.addView(sv, ViewGroup.LayoutParams(-1, -1))
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_CAPTURE) {
            if (resultCode == RESULT_OK && data != null) {
                startForegroundService(
                    Intent(this, CaptureService::class.java).putExtra("code", resultCode).putExtra("data", data)
                )
            } else {
                Toast.makeText(this, "Без захвата экрана макрос не увидит миниигру", Toast.LENGTH_LONG).show()
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        val w = web
        if (w != null && w.canGoBack()) w.goBack() else moveTaskToBack(true)
    }

    override fun onDestroy() {
        web?.destroy()
        web = null
        super.onDestroy()
    }

    /** То, что панель может попросить у телефона. */
    inner class Js {
        @JavascriptInterface fun askAccess() {
            ui.post {
                Toast.makeText(this@MainActivity, "Найди «Рыбачка» в списке и включи", Toast.LENGTH_LONG).show()
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            }
        }

        @JavascriptInterface fun askCapture() {
            ui.post {
                val mpm = getSystemService(MediaProjectionManager::class.java)
                @Suppress("DEPRECATION")
                startActivityForResult(mpm.createScreenCaptureIntent(), REQ_CAPTURE)
            }
        }

        @JavascriptInterface fun pick(name: String) {
            val a = Bridge.access
            if (a == null) {
                ui.post { Toast.makeText(this@MainActivity, "Сначала включи управление касаниями", Toast.LENGTH_LONG).show() }
                return
            }
            a.startPick(name)
        }

        @JavascriptInterface fun snap() {
            ui.post { Toast.makeText(this@MainActivity, "Открываю игру, через 6 с сохраню кадр", Toast.LENGTH_LONG).show() }
            Bridge.launchGame()
            Thread {
                try { Thread.sleep(6000) } catch (t: InterruptedException) { return@Thread }
                val ok = Bridge.saveFrame("snap")
                Bridge.access?.toast(if (ok) "Кадр сохранён: Галерея → Pictures/Rybachka" else "Кадр сохранить не вышло (захват экрана включён?)")
            }.start()
        }

        @JavascriptInterface fun launchGame() {
            if (!Bridge.launchGame()) {
                ui.post { Toast.makeText(this@MainActivity, "Roblox не найден на телефоне", Toast.LENGTH_LONG).show() }
            }
        }

        @SuppressLint("BatteryLife")
        @JavascriptInterface fun battery() {
            ui.post {
                try {
                    startActivity(
                        Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
                    )
                } catch (t: Throwable) {
                    startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                }
            }
        }

        @JavascriptInterface fun quit() {
            ui.post {
                Bridge.py("stop")
                stopService(Intent(this@MainActivity, CaptureService::class.java))
                stopService(Intent(this@MainActivity, CoreService::class.java))
                finishAndRemoveTask()
                Process.killProcess(Process.myPid())
            }
        }
    }

    companion object {
        const val REQ_CAPTURE = 1001
    }
}
