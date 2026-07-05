package com.nothing.airshare

import android.os.Environment
import android.util.Log
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.ServerSocket
import java.net.Socket
import java.net.InetAddress
import kotlin.concurrent.thread

object FileTransferService {
    var port: Int = 53317
    var securityPin: String = "1234"
    private var serverSocket: ServerSocket? = null
    private var isRunning = false

    // Callback handlers to bind to MainActivity UI
    var incomingTransferHandler: ((sender: String, fileName: String, fileSize: Long, callback: (Boolean) -> Unit) -> Unit)? = null
    var progressHandler: ((progress: Double) -> Unit)? = null
    var statusHandler: ((String) -> Unit)? = null

    fun startServer() {
        if (isRunning) return
        isRunning = true
        
        thread {
            // Retry binding with exponential backoff (K5)
            var bindAttempt = 0
            val maxBindAttempts = 3
            var bound = false
            
            while (bindAttempt < maxBindAttempts && !bound) {
                try {
                    serverSocket = ServerSocket(port).apply {
                        reuseAddress = true
                        soTimeout = 1000
                    }
                    Log.d("TransferService", "TCP Server listening on port $port")
                    bound = true
                } catch (e: Exception) {
                    bindAttempt++
                    Log.e("TransferService", "Server bind failed (attempt $bindAttempt/$maxBindAttempts): ${e.message}")
                    if (bindAttempt < maxBindAttempts) {
                        val backoffMs = 1000L * (1 shl (bindAttempt - 1))  // 1s, 2s, 4s
                        Log.d("TransferService", "Retrying bind in ${backoffMs}ms...")
                        try { Thread.sleep(backoffMs) } catch (_: InterruptedException) {}
                    }
                }
            }
            
            if (!bound) {
                Log.e("TransferService", "Failed to bind server after $maxBindAttempts attempts")
                isRunning = false
                return@thread
            }
            
            while (isRunning) {
                try {
                    val clientSocket = serverSocket?.accept()
                    if (clientSocket != null) {
                        thread {
                            handleIncomingConnection(clientSocket)
                        }
                    }
                } catch (e: java.net.SocketTimeoutException) {
                    // Expected, allows loop to check isRunning
                }
            }
        }
    }

    fun stopServer() {
        isRunning = false
        try {
            serverSocket?.close()
        } catch (e: Exception) {
            Log.e("TransferService", "Error closing server: ${e.message}")
        }
    }

    private fun handleIncomingConnection(socket: Socket) {
        try {
            socket.soTimeout = 30000
            val dis = DataInputStream(socket.getInputStream())
            val dos = DataOutputStream(socket.getOutputStream())

            // 1. Read metadata length (4 bytes big-endian)
            val metaLength = dis.readInt()
            if (metaLength <= 0 || metaLength > 1024 * 1024) {
                socket.close()
                return
            }

            // 2. Read metadata JSON
            val metaBytes = ByteArray(metaLength)
            dis.readFully(metaBytes)
            val metaJsonStr = String(metaBytes, Charsets.UTF_8)
            val metadata = JSONObject(metaJsonStr)

            val senderName = metadata.optString("senderName", "Unknown Device")
            val fileName = metadata.optString("fileName", "file.bin")
            val fileSize = metadata.optLong("fileSize", 0L)
            val providedPin = metadata.optString("pin", "")

            if (providedPin != securityPin) {
                Log.e("TransferService", "Unauthorized transfer attempt (Invalid PIN)")
                updateStatus("Unauthorized attempt rejected")
                dos.writeByte(0x02) // Reject
                dos.flush()
                socket.close()
                return
            }

            Log.d("TransferService", "Incoming transfer: $fileName ($fileSize bytes) from $senderName")
            updateStatus("Prompting for: $fileName")

            // 3. Prompt user via callback
            var accepted = false
            val lock = Object()
            var completedPrompt = false

            incomingTransferHandler?.invoke(senderName, fileName, fileSize) { result ->
                synchronized(lock) {
                    accepted = result
                    completedPrompt = true
                    lock.notifyAll()
                }
            }

            // Wait for user approval
            synchronized(lock) {
                while (!completedPrompt) {
                    try {
                        lock.wait()
                    } catch (e: InterruptedException) {
                        e.printStackTrace()
                    }
                }
            }

            // 4. Send response
            if (accepted) {
                dos.writeByte(0x01) // Accept code
                dos.flush()
                Log.d("TransferService", "Transfer accepted. Receiving file data...")
                updateStatus("Receiving: $fileName")

                // 5. Stream file bytes
                val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                val targetDir = File(downloadsDir, "NothingDrop")
                if (!targetDir.exists()) {
                    targetDir.mkdirs()
                }
                
                // Prevent duplicate naming conflicts
                var targetFile = File(targetDir, fileName)
                var counter = 1
                while (targetFile.exists()) {
                    val baseName = targetFile.nameWithoutExtension
                    val ext = targetFile.extension
                    val newName = if (ext.isNotEmpty()) "$baseName-$counter.$ext" else "$baseName-$counter"
                    targetFile = File(targetDir, newName)
                    counter++
                }

                val fos = FileOutputStream(targetFile)
                val buffer = ByteArray(262144)  // 256KB buffer for optimal Wi-Fi throughput (L5)
                var bytesRead: Int
                var totalBytesRead = 0L

                while (totalBytesRead < fileSize) {
                    val remain = fileSize - totalBytesRead
                    val toRead = if (remain < buffer.size) remain.toInt() else buffer.size
                    bytesRead = dis.read(buffer, 0, toRead)
                    if (bytesRead == -1) break
                    fos.write(buffer, 0, bytesRead)
                    totalBytesRead += bytesRead

                    val progress = if (fileSize > 0) totalBytesRead.toDouble() / fileSize else 0.0
                    progressHandler?.invoke(progress)
                }

                fos.flush()
                fos.close()
                Log.d("TransferService", "Successfully received file: ${targetFile.absolutePath}")
                updateStatus("Saved to: Downloads/NothingDrop")
                progressHandler?.invoke(1.0)
            } else {
                dos.writeByte(0x02) // Reject code
                dos.flush()
                Log.d("TransferService", "Transfer rejected.")
                updateStatus("Rejected transfer from $senderName")
            }

            socket.close()
        } catch (e: Exception) {
            Log.e("TransferService", "Connection handle error: ${e.message}")
            updateStatus("Transfer failed")
            try {
                socket.close()
            } catch (ex: Exception) {}
        }
    }

    fun sendFile(file: File, host: InetAddress, port: Int) {
        thread {
            try {
                updateStatus("Connecting to receiver...")
                val socket = Socket(host, port)
                socket.soTimeout = 30000
                val dis = DataInputStream(socket.getInputStream())
                val dos = DataOutputStream(socket.getOutputStream())

                // 1. Prepare Metadata JSON
                val metadata = JSONObject().apply {
                    put("senderName", android.os.Build.MODEL)
                    put("fileName", file.name)
                    put("fileSize", file.length())
                    put("pin", securityPin)
                }
                val metaBytes = metadata.toString().toByteArray(Charsets.UTF_8)

                // 2. Send Metadata length + JSON
                dos.writeInt(metaBytes.size)
                dos.write(metaBytes)
                dos.flush()

                updateStatus("Waiting for approval...")

                // 3. Wait for Accept/Reject code
                val response = dis.readByte().toInt()
                if (response == 0x01) {
                    updateStatus("Sending: ${file.name}")
                    
                    // 4. Stream file bytes
                    val fis = FileInputStream(file)
                    val buffer = ByteArray(262144)  // 256KB buffer (L5)
                    var bytesRead: Int
                    var totalBytesSent = 0L
                    val totalSize = file.length()

                    while (fis.read(buffer).also { bytesRead = it } != -1) {
                        dos.write(buffer, 0, bytesRead)
                        totalBytesSent += bytesRead
                        val progress = if (totalSize > 0) totalBytesSent.toDouble() / totalSize else 0.0
                        progressHandler?.invoke(progress)
                    }

                    dos.flush()
                    fis.close()
                    Log.d("TransferService", "File sent successfully!")
                    updateStatus("Sent: ${file.name}")
                    progressHandler?.invoke(1.0)
                } else {
                    Log.d("TransferService", "Receiver rejected the file.")
                    updateStatus("Receiver rejected transfer")
                }

                socket.close()
            } catch (e: Exception) {
                Log.e("TransferService", "Send file error: ${e.message}")
                updateStatus("Send failed: ${e.localizedMessage}")
            }
        }
    }

    private fun updateStatus(msg: String) {
        statusHandler?.invoke(msg)
    }

    /**
     * Stream a file directly from a content URI without materializing to cache (K3).
     * Reduces memory usage and eliminates the latency of copying large files to disk.
     */
    fun sendFileFromUri(context: android.content.Context, uri: android.net.Uri, host: InetAddress, port: Int) {
        thread {
            try {
                // Get file name and size from ContentResolver
                var fileName = "file.bin"
                var fileSize = 0L
                val cursor = context.contentResolver.query(uri, null, null, null, null)
                cursor?.use {
                    if (it.moveToFirst()) {
                        val nameIndex = it.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                        val sizeIndex = it.getColumnIndex(android.provider.OpenableColumns.SIZE)
                        if (nameIndex != -1) fileName = it.getString(nameIndex)
                        if (sizeIndex != -1) fileSize = it.getLong(sizeIndex)
                    }
                }

                updateStatus("Connecting to receiver...")
                val socket = Socket(host, port)
                socket.soTimeout = 30000
                val dis = DataInputStream(socket.getInputStream())
                val dos = DataOutputStream(socket.getOutputStream())

                val metadata = org.json.JSONObject().apply {
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
                if (response == 0x01) {
                    updateStatus("Sending: $fileName")
                    val inputStream = context.contentResolver.openInputStream(uri)
                        ?: throw Exception("Cannot open input stream for URI")
                    val buffer = ByteArray(262144)  // 256KB buffer (L5)
                    var bytesRead: Int
                    var totalBytesSent = 0L

                    while (inputStream.read(buffer).also { bytesRead = it } != -1) {
                        dos.write(buffer, 0, bytesRead)
                        totalBytesSent += bytesRead
                        val progress = if (fileSize > 0) totalBytesSent.toDouble() / fileSize else 0.0
                        progressHandler?.invoke(progress)
                    }

                    dos.flush()
                    inputStream.close()
                    Log.d("TransferService", "File sent successfully via URI stream!")
                    updateStatus("Sent: $fileName")
                    progressHandler?.invoke(1.0)
                } else {
                    Log.d("TransferService", "Receiver rejected the file.")
                    updateStatus("Receiver rejected transfer")
                }

                socket.close()
            } catch (e: Exception) {
                Log.e("TransferService", "Send file from URI error: ${e.message}")
                updateStatus("Send failed: ${e.localizedMessage}")
            }
        }
    }
}
