package com.nothing.airshare

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.ServiceCompat
import java.net.InetAddress

/**
 * Foreground service that keeps sync alive when the app is backgrounded or
 * closed. It owns the single NSD discovery, the file-transfer server, the
 * persistent [MacSession], and the clipboard + battery bridges.
 *
 * The old design ran all of this inside [MainActivity], so sync died the moment
 * the Activity was destroyed — this fixes that.
 */
class SyncService : Service(), NsdHelper.NsdListener {
    private lateinit var nsdHelper: NsdHelper
    private var clipboard: ClipboardManager? = null
    private var clipListener: ClipboardManager.OnPrimaryClipChangedListener? = null
    private var batteryReceiver: BroadcastReceiver? = null

    companion object {
        const val CHANNEL_ID = "nothing_airshare_sync"
        const val NOTIF_ID = 42

        /** Devices discovered on the LAN, shared with the UI (name -> host,port). */
        val discoveredDevices = java.util.concurrent.ConcurrentHashMap<String, Pair<InetAddress, Int>>()
        /** Invoked (on any thread) whenever the discovered-device set changes. */
        @Volatile var devicesChanged: (() -> Unit)? = null

        fun start(context: Context) {
            val intent = Intent(context, SyncService::class.java)
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()

        val prefs = getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
        val localPort = prefs.getInt("local_port", 53317)
        val pin = prefs.getString("pref_security_pin", "1234") ?: "1234"

        // 1. File server
        FileTransferService.port = localPort
        FileTransferService.securityPin = pin
        FileTransferService.startServer()

        // 2. Duplex session to the Mac
        MacSession.init(this)

        // 3. NSD discovery + advertising (single owner)
        nsdHelper = NsdHelper(this, this)
        nsdHelper.registerService(localPort)
        nsdHelper.discoverServices()

        // 4. Bridges
        registerClipboardListener()
        registerBatteryReceiver()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        ServiceCompat.startForeground(this, NOTIF_ID, buildNotification(), type)
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        clipListener?.let { clipboard?.removePrimaryClipChangedListener(it) }
        batteryReceiver?.let { runCatching { unregisterReceiver(it) } }
        nsdHelper.stop()
        MacSession.stop()
        FileTransferService.stopServer()
    }

    // ── NSD callbacks: point the session at any discovered Mac ────────────────

    override fun onDeviceDiscovered(name: String, host: InetAddress, port: Int) {
        discoveredDevices[name] = Pair(host, port)
        devicesChanged?.invoke()
        // Connect to a Mac endpoint (Mac advertises "Mac Nothing Share").
        if (name.contains("Mac", ignoreCase = true)) {
            MacSession.setTarget(host.hostAddress ?: return, port)
        }
    }

    override fun onDeviceRemoved(name: String) {
        discoveredDevices.remove(name)
        devicesChanged?.invoke()
    }

    // ── Bridges ───────────────────────────────────────────────────────────────

    private fun registerClipboardListener() {
        val cb = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard = cb
        val listener = ClipboardManager.OnPrimaryClipChangedListener {
            val clip = cb.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val text = clip.getItemAt(0).text?.toString() ?: return@OnPrimaryClipChangedListener
                MacSession.onLocalClipboardChanged(text)
            }
        }
        cb.addPrimaryClipChangedListener(listener)
        clipListener = listener
    }

    private fun registerBatteryReceiver() {
        val receiver = object : BroadcastReceiver() {
            private var lastPct = -1
            private var lastCharging = false
            private var lastSend = 0L
            override fun onReceive(context: Context, intent: Intent) {
                val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
                val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
                val pct = if (scale > 0) level * 100 / scale else -1
                val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
                val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
                    status == BatteryManager.BATTERY_STATUS_FULL
                if (pct == lastPct && charging == lastCharging) return
                lastPct = pct; lastCharging = charging
                // Debounce to at most once / 30s, but still send the latest value.
                val now = System.currentTimeMillis()
                if (now - lastSend < 30_000L && lastSend != 0L) return
                lastSend = now
                MacSession.sendBattery(pct, charging)
            }
        }
        registerReceiver(receiver, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        batteryReceiver = receiver
    }

    // ── Notification ──────────────────────────────────────────────────────────

    private fun createChannel() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID, "Nothing AirShare Sync", NotificationManager.IMPORTANCE_LOW
        ).apply { description = "Keeps clipboard and file sync running" }
        nm.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val tap = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Nothing AirShare active")
            .setContentText("Clipboard & file sync running")
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentIntent(tap)
            .setOngoing(true)
            .build()
    }
}
