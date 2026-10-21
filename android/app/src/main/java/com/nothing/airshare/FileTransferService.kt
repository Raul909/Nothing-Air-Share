package com.nothing.airshare

import android.content.Context
import android.media.MediaScannerConnection
import android.os.Environment
import android.util.Log
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

object FileTransferService {
    private const val TAG = "TransferService"
    // The receiving side shows an Accept/Decline prompt (the Mac's gives up after
    // 100s); wait a little longer than that before treating it as declined.
    private const val APPROVAL_TIMEOUT_MS = 120_000L
    private const val IO_TIMEOUT_MS = 30_000
    private const val BUFFER_SIZE = 262144  // 256KB buffer for optimal Wi-Fi throughput (L5)

    @Volatile var port: Int = 53317
    @Volatile var securityPin: String = "1234"
    /** Used to index received files so they show up in Files/Photos right away. */
    @Volatile var appContext: Context? = null
    @Volatile private var serverSocket: ServerSocket? = null
    @Volatile private var isRunning = false
    // Bumped on every start/stop so a server thread from a previous start()
    // can never keep accepting after a restart (e.g. a local-port change).
    @Volatile private var generation = 0

    // Callback handlers to bind to MainActivity UI
    @Volatile var incomingTransferHandler: ((sender: String, fileName: String, fileSize: Long, callback: (Boolean) -> Unit) -> Unit)? = null
    @Volatile var progressHandler: ((progress: Double) -> Unit)? = null
    @Volatile var statusHandler: ((String) -> Unit)? = null

    @Synchronized
    fun startServer() {
        if (isRunning) return
        isRunning = true
        val gen = ++generation
        thread(name = "FileTransferServer") { serve(gen) }
    }

    @Synchronized
    fun stopServer() {
        isRunning = false
        generation++
        try {
            serverSocket?.close()
        } catch (e: Exception) {
            Log.e(TAG, "Error closing server: ${e.message}")
        }
        serverSocket = null
    }

    private fun serve(gen: Int) {
        // Retry binding with exponential backoff (K5)
        var server: ServerSocket? = null
        var bindAttempt = 0
        val maxBindAttempts = 5
        while (server == null && gen == generation) {
            try {
                // reuseAddress only takes effect if set before bind().
                server = ServerSocket().apply {
                    reuseAddress = true
                    bind(InetSocketAddress(port))
                }
            } catch (e: Exception) {
                bindAttempt++
                Log.e(TAG, "Server bind failed (attempt $bindAttempt/$maxBindAttempts): ${e.message}")
                if (bindAttempt >= maxBindAttempts) {
                    synchronized(this) { if (gen == generation) isRunning = false }
                    return
                }
                try { Thread.sleep(1000L shl (bindAttempt - 1)) } catch (_: InterruptedException) {}
            }
        }
        if (server == null) return
        synchronized(this) {
            if (gen != generation) {
                server.close()
                return
            }
            serverSocket = server
        }
        Log.d(TAG, "TCP Server listening on port $port")

        // accept() blocks until a client arrives or stopServer() closes the socket
        // (which throws here). The old loop polled with a 1s timeout forever, and
        // the SocketException from close() went uncaught and crashed the app.
        try {
            while (gen == generation) {
                val clientSocket = server.accept()
                thread(name = "FileTransfer-in") { handleIncomingConnection(clientSocket) }
            }
        } catch (e: Exception) {
            if (gen == generation) Log.e(TAG, "Server stopped unexpectedly: ${e.message}")
        } finally {
            try { server.close() } catch (_: Exception) {}
        }
    }

    /** Reduce a peer-supplied name to a plain file name ('../../x' can't escape). */
    fun safeFileName(name: String?): String {
        val base = (name ?: "").substringAfterLast('/').substringAfterLast('\\')
            .filter { it >= ' ' && it != '\u007f' }
            .trim().trimStart('.')
        return if (base.isEmpty()) "file.bin" else base.take(200)
    }

    private fun handleIncomingConnection(socket: Socket) {
        var partFile: File? = null
        try {
            socket.use {
                socket.soTimeout = IO_TIMEOUT_MS
                val dis = DataInputStream(socket.getInputStream())
                val dos = DataOutputStream(socket.getOutputStream())

                // 1. Read metadata length (4 bytes big-endian)
                val metaLength = dis.readInt()
                if (metaLength <= 0 || metaLength > 1024 * 1024) return

                // 2. Read metadata JSON
                val metaBytes = ByteArray(metaLength)
                dis.readFully(metaBytes)
                val metadata = JSONObject(String(metaBytes, Charsets.UTF_8))

                val senderName = metadata.optString("senderName", "Unknown Device").take(64)
                val fileName = safeFileName(metadata.optString("fileName", "file.bin"))
                val fileSize = metadata.optLong("fileSize", 0L)
                val providedPin = metadata.optString("pin", "")

                if (providedPin != securityPin || fileSize < 0) {
                    Log.e(TAG, "Unauthorized transfer attempt (Invalid PIN)")
                    updateStatus("Unauthorized attempt rejected")
                    dos.writeByte(0x02) // Reject
                    dos.flush()
                    return
                }

                Log.d(TAG, "Incoming transfer: $fileName ($fileSize bytes) from $senderName")
                updateStatus("Prompting for: $fileName")

                // 3. Prompt user via callback. With no UI attached (app closed,
                // service still running) nobody can answer, so decline instead of
                // parking this thread forever; never wait longer than the timeout.
                val answered = CountDownLatch(1)
                val accepted = AtomicBoolean(false)
                val handler = incomingTransferHandler
                if (handler != null) {
                    handler.invoke(senderName, fileName, fileSize) { result ->
                        accepted.set(result)
                        answered.countDown()
                    }
                    if (!answered.await(APPROVAL_TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
                        Log.d(TAG, "No answer to transfer prompt; declining")
                    }
                } else {
                    Log.d(TAG, "No UI to approve the transfer; declining")
                }

                // 4. Send response
                if (!accepted.get()) {
                    dos.writeByte(0x02) // Reject code
                    dos.flush()
                    Log.d(TAG, "Transfer rejected.")
                    updateStatus("Rejected transfer from $senderName")
                    return
                }
                dos.writeByte(0x01) // Accept code
                dos.flush()
                Log.d(TAG, "Transfer accepted. Receiving file data...")
                updateStatus("Receiving: $fileName")

                // 5. Stream into a hidden .part file; it's renamed only once complete
                val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                val targetDir = File(downloadsDir, "NothingDrop")
                if (!targetDir.exists()) {
                    targetDir.mkdirs()
                }
                val targetFile = uniqueFile(targetDir, fileName)
                val part = File(targetDir, ".${targetFile.name}.part")
                partFile = part

                var totalBytesRead = 0L
                val progress = ProgressReporter(fileSize)
                FileOutputStream(part).use { fos ->
                    val buffer = ByteArray(BUFFER_SIZE)
                    while (totalBytesRead < fileSize) {
                        val toRead = minOf(buffer.size.toLong(), fileSize - totalBytesRead).toInt()
                        val bytesRead = dis.read(buffer, 0, toRead)
                        if (bytesRead == -1) break
                        fos.write(buffer, 0, bytesRead)
                        totalBytesRead += bytesRead
                        progress.report(totalBytesRead)
                    }
                }
                if (totalBytesRead != fileSize) {
                    throw java.io.IOException("Stream ended after $totalBytesRead/$fileSize bytes")
                }
                if (!part.renameTo(targetFile)) {
                    throw java.io.IOException("Could not save ${targetFile.name}")
                }
                partFile = null
                appContext?.let { ctx ->
                    MediaScannerConnection.scanFile(ctx, arrayOf(targetFile.absolutePath), null, null)
                }
                Log.d(TAG, "Successfully received file: ${targetFile.absolutePath}")
                updateStatus("Saved to: Downloads/NothingDrop")
                progressHandler?.invoke(1.0)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Connection handle error: ${e.message}")
            updateStatus("Transfer failed")
            progressHandler?.invoke(1.0)
        } finally {
            partFile?.delete()  // never leave a truncated file behind
        }
    }

    private fun uniqueFile(dir: File, fileName: String): File {
        // Prevent duplicate naming conflicts
        var targetFile = File(dir, fileName)
        val baseName = targetFile.nameWithoutExtension
        val ext = targetFile.extension
        var counter = 1
        while (targetFile.exists()) {
            val newName = if (ext.isNotEmpty()) "$baseName-$counter.$ext" else "$baseName-$counter"
            targetFile = File(dir, newName)
            counter++
        }
        return targetFile
    }

    private fun updateStatus(msg: String) {
        statusHandler?.invoke(msg)
    }

    /** Forwards progress only when the whole percentage changes, instead of
     *  posting a UI update for every 256KB chunk. */
    private class ProgressReporter(private val total: Long) {
        private var lastPercent = -1
        fun report(done: Long) {
            if (total <= 0) return
            val percent = (done * 100 / total).toInt()
            if (percent != lastPercent) {
                lastPercent = percent
                progressHandler?.invoke(done.toDouble() / total)
            }
        }
    }

    /**
     * Stream a file directly from a content URI without materializing to cache (K3).
     * Reduces memory usage and eliminates the latency of copying large files to disk.
     * Only providers that don't report a size get spooled to cache first, because
     * the receiver needs the exact length up front.
     */
    fun sendFileFromUri(context: Context, uri: android.net.Uri, host: String, port: Int) {
        thread(name = "FileTransfer-out") {
            var spooled: File? = null
            try {
                // Get file name and size from ContentResolver
                var fileName = "file.bin"
                var fileSize = -1L
                context.contentResolver.query(uri, null, null, null, null)?.use {
                    if (it.moveToFirst()) {
                        val nameIndex = it.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                        val sizeIndex = it.getColumnIndex(android.provider.OpenableColumns.SIZE)
                        if (nameIndex != -1) fileName = it.getString(nameIndex) ?: fileName
                        if (sizeIndex != -1 && !it.isNull(sizeIndex)) fileSize = it.getLong(sizeIndex)
                    }
                }
                if (fileSize <= 0) {
                    val tmp = File.createTempFile("send", ".bin", context.cacheDir)
                    spooled = tmp
                    context.contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(tmp).use { input.copyTo(it, BUFFER_SIZE) }
                    } ?: throw Exception("Cannot open input stream for URI")
                    fileSize = tmp.length()
                }

                updateStatus("Connecting to receiver...")
                Socket().use { socket ->
                    socket.connect(InetSocketAddress(host, port), 10_000)
                    socket.soTimeout = (APPROVAL_TIMEOUT_MS + 15_000L).toInt()
                    val dis = DataInputStream(socket.getInputStream())
                    val dos = DataOutputStream(socket.getOutputStream())

                    val metadata = JSONObject().apply {
                        put("senderName", android.os.Build.MODEL)
                        put("fileName", fileName)
                        put("fileSize", fileSize)
                        put("pin", securityPin)
                    }
                    val metaBytes = metadata.toString().toByteArray(Charsets.UTF_8)
                    dos.writeInt(metaBytes.size)
                    dos.write(metaBytes)
                    dos.flush()

                    updateStatus("Waiting for approval...")
                    val response = dis.readByte().toInt()
                    if (response != 0x01) {
                        Log.d(TAG, "Receiver rejected the file.")
                        updateStatus("Receiver rejected transfer")
                        return@use
                    }
                    socket.soTimeout = IO_TIMEOUT_MS
                    updateStatus("Sending: $fileName")
                    val source: InputStream = spooled?.inputStream()
                        ?: context.contentResolver.openInputStream(uri)
                        ?: throw Exception("Cannot open input stream for URI")
                    val progress = ProgressReporter(fileSize)
                    source.use { input ->
                        val buffer = ByteArray(BUFFER_SIZE)
                        var totalBytesSent = 0L
                        while (true) {
                            val bytesRead = input.read(buffer)
                            if (bytesRead == -1) break
                            dos.write(buffer, 0, bytesRead)
                            totalBytesSent += bytesRead
                            progress.report(totalBytesSent)
                        }
                    }
                    dos.flush()
                    Log.d(TAG, "File sent successfully via URI stream!")
                    updateStatus("Sent: $fileName")
                    progressHandler?.invoke(1.0)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Send file from URI error: ${e.message}")
                updateStatus("Send failed: ${e.localizedMessage}")
                progressHandler?.invoke(1.0)
            } finally {
                spooled?.delete()
            }
        }
    }
}
