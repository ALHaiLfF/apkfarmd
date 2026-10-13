package app.sakura.fishing

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon

object Notif {
    private const val CH = "sakura"

    fun build(ctx: Context, text: String, withToggle: Boolean): Notification {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CH) == null) {
            nm.createNotificationChannel(NotificationChannel(CH, "Рыбачка", NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val b = Notification.Builder(ctx, CH)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("Рыбачка")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
        if (withToggle) {
            val t = PendingIntent.getService(
                ctx, 1, Intent(ctx, CoreService::class.java).setAction(CoreService.ACTION_TOGGLE),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            b.addAction(Notification.Action.Builder(Icon.createWithResource(ctx, R.drawable.ic_stat), "Старт / стоп", t).build())
        }
        return b.build()
    }
}
