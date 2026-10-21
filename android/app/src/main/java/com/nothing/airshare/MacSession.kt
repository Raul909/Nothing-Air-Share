package com.nothing.airshare

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * Persistent duplex connection to the macOS daemon — the single transport for
 * clipboard, DND, battery, trackpad and media. It replaces the old one-shot
 * command sockets and the ADB-shell clipboard polling.
 *
 * Wire format matches [FileTransferService] and the Mac's PeerSession:
 * a 4-byte big-endian length prefix + UTF-8 JSON, plus a 0x01 binary fast-path
 * for mouse-move. On connect the phone sends a `hello`; both ends heartbeat with
 * `ping`/`pong` so a dead socket is detected within ~35s.
 *
 * Singleton (like [FileTransferService]) so both [SyncService] and the UI can use it.
 */
object MacSession {
    private const val TAG = "MacSession"
    private const val HEARTBEAT_MS = 15_000L
    private const val TIMEOUT_MS = 35_000L
    private const val PROTO_VERSION = 1

    @Volatile private var appContext: Context? = null
    @Volatile private var targetHost: String? = null
    @Volatile private var targetPort: Int = 53317

    @Volatile private var socket: Socket? = null
    @Volatile private var dos: DataOutputStream? = null
    // All socket writes run on this single thread so any caller (incl. the UI
    // thread from the trackpad) can enqueue without NetworkOnMainThreadException.
    private val sender = Executors.newSingleThreadExecutor()

    @Volatile private var running = false
    @Volatile private var connected = false
    @Volatile private var lastRx = 0L
    private var worker: Thread? = null
    // Bumped on every start()/stop(). A worker only runs while its generation is
    // current, so a quick stop()+start() can't leave two loops connecting at once.
    @Volatile private var generation = 0
    // Wakes the reconnect backoff early (network came back, new target).
    private val retrySignal = Object()

    // Echo-suppression: the last clipboard text we sent or applied, so the local
    // clipboard listener doesn't bounce a value we just synced back to the Mac.
    @Volatile private var lastClip: String = ""

    /** Notified on the main thread when the connection state flips. */
    var connectionListener: ((connected: Boolean) -> Unit)? = null

    /** Invoked on the session thread right after each successful handshake. */
    @Volatile var onConnected: (() -> Unit)? = null

    val isConnected: Boolean get() = connected

    fun init(context: Context) {
        appContext = context.applicationContext
    }

    /** Point the session at a discovered Mac and (re)connect if the target changed. */
    @Synchronized
    fun setTarget(host: String, port: Int) {
        if (host == targetHost && port == targetPort && running) return
        targetHost = host
        targetPort = port
        Log.d(TAG, "Target set to $host:$port")
        start()
        if (!connected) reconnectNow()
    }

    @Synchronized
    fun start() {
        if (running) return
        running = true
        val gen = ++generation
        worker = thread(name = "MacSession") { runLoop(gen) }
    }

    @Synchronized
    fun stop() {
        running = false
        generation++
        reconnectNow()
        closeSocket()
        setConnected(false)
        worker = null
    }

    /** Skip the remaining reconnect backoff, e.g. when the network comes back. */
    fun reconnectNow() {
        synchronized(retrySignal) { retrySignal.notifyAll() }
    }

    private fun isCurrent(gen: Int) = running && gen == generation

    private fun runLoop(gen: Int) {
        var backoffMs = 1000L
        while (isCurrent(gen)) {
            val host = targetHost
            if (host == null) {
                waitForRetry(500); continue
            }
            var s: Socket? = null
            try {
                Log.d(TAG, "Connecting to $host:$targetPort")
                s = Socket()
                s.tcpNoDelay = true
                s.connect(InetSocketAddress(host, targetPort), 5000)
                s.soTimeout = TIMEOUT_MS.toInt()
                if (!isCurrent(gen)) break
                socket = s
                dos = DataOutputStream(s.getOutputStream())
                val dis = DataInputStream(s.getInputStream())

                sendJson(JSONObject().apply {
                    put("type", "hello")
                    put("name", Build.MODEL)
                    put("protoVersion", PROTO_VERSION)
                })
                setConnected(true)
                lastRx = System.currentTimeMillis()
                backoffMs = 1000L
                startHeartbeat(s)
                onConnected?.invoke()

                // Blocking read loop for inbound frames (JSON only from the Mac).
                while (isCurrent(gen)) {
                    val len = dis.readInt()
                    if (len <= 0 || len > 1_000_000) break
                    val buf = ByteArray(len)
                    dis.readFully(buf)
                    lastRx = System.currentTimeMillis()
                    handleInbound(JSONObject(String(buf, Charsets.UTF_8)))
                }
            } catch (e: Exception) {
                Log.d(TAG, "Session dropped: ${e.message}")
            } finally {
                // Only tear down shared state if this loop is still the current
                // one; a newer loop may already have installed its own socket.
                if (gen == generation) {
                    setConnected(false)
                    closeSocket()
                } else {
                    try { s?.close() } catch (_: Exception) {}
                }
            }
            if (isCurrent(gen)) {
                waitForRetry(backoffMs)
                backoffMs = (backoffMs * 2).coerceAtMost(15_000L)
            }
        }
    }

    /** One heartbeat thread per connection; it exits as soon as that socket is
     *  replaced or closed (it used to survive quick reconnects and pile up). */
    private fun startHeartbeat(s: Socket) {
        thread(name = "MacSession-hb") {
            while (socket === s && !s.isClosed) {
                sleep(HEARTBEAT_MS)
                if (socket !== s || s.isClosed) break
                if (System.currentTimeMillis() - lastRx > TIMEOUT_MS) {
                    Log.d(TAG, "Heartbeat timeout — dropping socket")
                    try { s.close() } catch (_: Exception) {}
                    break
                }
                sendJson(JSONObject().apply { put("type", "ping") })
            }
        }
    }

    private fun waitForRetry(ms: Long) {
        try {
            synchronized(retrySignal) { retrySignal.wait(ms) }
        } catch (_: InterruptedException) {}
    }

    private fun handleInbound(msg: JSONObject) {
        when (msg.optString("type")) {
            "clip" -> if (msg.optString("format", "text") == "text") {
                applyRemoteClip(msg.optString("data", ""))
            }
            "dnd" -> Log.d(TAG, "Mac DND: ${msg.optBoolean("on", false)}")
            "ping" -> sendJson(JSONObject().apply { put("type", "pong") })
            "pong" -> { /* liveness refreshed via lastRx */ }
            "hello" -> Log.d(TAG, "Handshake with ${msg.optString("name", "Mac")}")
            "find_phone" -> appContext?.let { ctx -> Handler(Looper.getMainLooper()).post { ClipboardReceiver.ringPhone(ctx) } }
        }
    }

    // ── Outbound API ─────────────────────────────────────────────────────────

    /** Called by the clipboard listener; sends only genuinely-new local copies. */
    fun onLocalClipboardChanged(text: String) {
        if (text.isEmpty() || text == lastClip) return
        lastClip = text
        sendJson(JSONObject().apply {
            put("type", "clip")
            put("format", "text")
            put("data", text)
        })
    }

    fun sendBattery(level: Int, charging: Boolean) {
        sendJson(JSONObject().apply {
            put("type", "battery")
            put("level", level)
            put("charging", charging)
        })
    }

    fun sendMediaKey(key: String) {
        sendJson(JSONObject().apply {
            put("type", "media_key")
            put("key", key)
        })
    }

    fun sendMouseClick() {
        sendJson(JSONObject().apply { put("type", "mouse_click") })
    }

    fun sendMouseRightClick() {
        sendJson(JSONObject().apply { put("type", "mouse_right_click") })
    }

    fun sendMouseDown() {
        sendJson(JSONObject().apply { put("type", "mouse_down") })
    }

    fun sendMouseUp() {
        sendJson(JSONObject().apply { put("type", "mouse_up") })
    }

    /** Binary move/scroll fast path: 1-byte opcode + dx + dy (float32 BE) = 9 bytes. */
    fun sendDeltaBinary(opcode: Byte, dx: Float, dy: Float) {
        sender.execute {
            val out = dos ?: return@execute
            try {
                val buf = ByteBuffer.allocate(9).order(ByteOrder.BIG_ENDIAN)
                buf.put(opcode); buf.putFloat(dx); buf.putFloat(dy)
                out.write(buf.array()); out.flush()
            } catch (e: Exception) {
                Log.e(TAG, "binary delta failed: ${e.message}"); closeSocket()
            }
        }
    }

    fun sendJson(msg: JSONObject) {
        sender.execute {
            val out = dos ?: return@execute
            try {
                val bytes = msg.toString().toByteArray(Charsets.UTF_8)
                out.writeInt(bytes.size); out.write(bytes); out.flush()
            } catch (e: Exception) {
                Log.e(TAG, "send failed: ${e.message}"); closeSocket()
            }
        }
    }

    // ── Internals ────────────────────────────────────────────────────────────

    private fun applyRemoteClip(text: String) {
        if (text.isEmpty()) return
        val ctx = appContext ?: return
        val prefs = ctx.getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("pref_clipboard_sync", true)) return
        lastClip = text  // suppress the echo before we mutate the clipboard
        Handler(Looper.getMainLooper()).post {
            try {
                val cb = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cb.setPrimaryClip(ClipData.newPlainText("Nothing AirShare", text))
            } catch (e: Exception) {
                Log.e(TAG, "apply clip failed: ${e.message}")
            }
        }
    }

    private fun setConnected(value: Boolean) {
        if (connected == value) return
        connected = value
        Handler(Looper.getMainLooper()).post { connectionListener?.invoke(value) }
    }

    @Synchronized
    private fun closeSocket() {
        try { dos?.close() } catch (_: Exception) {}
        try { socket?.close() } catch (_: Exception) {}
        dos = null
        socket = null
    }

    private fun sleep(ms: Long) = try { Thread.sleep(ms) } catch (_: InterruptedException) {}
}
