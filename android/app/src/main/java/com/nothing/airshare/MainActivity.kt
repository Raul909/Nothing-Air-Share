package com.nothing.airshare

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.setPadding
import com.nothing.airshare.databinding.ActivityMainBinding
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.InetAddress

class MainActivity : AppCompatActivity(), NsdHelper.NsdListener {
    private lateinit var binding: ActivityMainBinding
    private lateinit var nsdHelper: NsdHelper
    private val discoveredDevices = mutableMapOf<String, Pair<InetAddress, Int>>()
    private var selectedDeviceTarget: Pair<InetAddress, Int>? = null
    private lateinit var clipboard: ClipboardManager
    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        updateClipboardUI()
    }

    private val handler = Handler(Looper.getMainLooper())
    private val checkFolderRunnable = object : Runnable {
        override fun run() {
            updateDeviceListUI()
            handler.postDelayed(this, 1000)
        }
    }

    // Register a file picker launcher for direct P2P transfer
    private val filePickerLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null && selectedDeviceTarget != null) {
            try {
                val tempFile = getFileFromUri(this, uri)
                val target = selectedDeviceTarget!!
                FileTransferService.sendFile(tempFile, target.first, target.second)
            } catch (e: Exception) {
                Toast.makeText(this, "Failed to prepare file: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        supportActionBar?.hide()

        // Initialize clipboard manager and listener
        clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.addPrimaryClipChangedListener(clipboardListener)
        updateClipboardUI()

        // Handle incoming share intents
        handleSendIntent(intent)

        // 1. Initialize NSD Bonjour Discovery & Advertising
        nsdHelper = NsdHelper(this, this)
        nsdHelper.registerService(53317)
        nsdHelper.discoverServices()

        // 2. Initialize TCP Server
        FileTransferService.startServer()

        // 3. Bind File Transfer Callbacks to UI
        FileTransferService.progressHandler = { progress ->
            runOnUiThread {
                binding.progressBarTransfer.visibility = View.VISIBLE
                binding.progressBarTransfer.progress = (progress * 100).toInt()
                if (progress >= 1.0) {
                    binding.progressBarTransfer.visibility = View.GONE
                }
            }
        }

        FileTransferService.statusHandler = { msg ->
            runOnUiThread {
                binding.tvStatus.text = msg
            }
        }

        FileTransferService.incomingTransferHandler = { sender, fileName, fileSize, callback ->
            runOnUiThread {
                AlertDialog.Builder(this)
                    .setTitle("Incoming File Share")
                    .setMessage("Accept file '$fileName' (${formatFileSize(fileSize)}) from $sender?")
                    .setPositiveButton("Accept") { _, _ ->
                        callback(true)
                    }
                    .setNegativeButton("Decline") { _, _ ->
                        callback(false)
                    }
                    .setCancelable(false)
                    .show()
            }
        }

        // Bind Clipboard operations
        binding.btnCopy.setOnClickListener {
            val text = binding.etInput.text.toString()
            if (text.isNotEmpty()) {
                val clip = ClipData.newPlainText("Nothing AirShare", text)
                clipboard.setPrimaryClip(clip)
                Toast.makeText(this, "Copied to Clipboard", Toast.LENGTH_SHORT).show()
                binding.etInput.setText("")
            }
        }

        binding.btnPaste.setOnClickListener {
            val clip = clipboard.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val text = clip.getItemAt(0).text
                binding.tvStatus.text = text
            } else {
                binding.tvStatus.text = "Clipboard Empty"
            }
        }

        // Start polling the outgoing folder and updating UI
        handler.post(checkFolderRunnable)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleSendIntent(intent)
    }

    private fun handleSendIntent(intent: Intent) {
        val action = intent.action
        val type = intent.type
        
        if (Intent.ACTION_SEND == action && type != null) {
            if (intent.hasExtra(Intent.EXTRA_STREAM)) {
                (intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))?.let { uri ->
                    saveSharedFileToSyncFolder(uri)
                }
            } else if (intent.hasExtra(Intent.EXTRA_TEXT)) {
                intent.getStringExtra(Intent.EXTRA_TEXT)?.let { text ->
                    val clip = ClipData.newPlainText("Shared Text", text)
                    clipboard.setPrimaryClip(clip)
                    Toast.makeText(this, "Copied to Clipboard Helper", Toast.LENGTH_SHORT).show()
                }
            }
        } else if (Intent.ACTION_SEND_MULTIPLE == action && type != null) {
            intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris ->
                for (uri in uris) {
                    saveSharedFileToSyncFolder(uri)
                }
            }
        }
    }

    private fun saveSharedFileToSyncFolder(uri: Uri) {
        try {
            val targetDir = File(getExternalFilesDir(null), "ToMac")
            if (!targetDir.exists()) {
                targetDir.mkdirs()
            }
            val fileName = getFileName(this, uri)
            val outputFile = File(targetDir, fileName)
            
            val parcelFileDescriptor = contentResolver.openFileDescriptor(uri, "r")
            val fileDescriptor = parcelFileDescriptor?.fileDescriptor ?: return
            val inputStream = FileInputStream(fileDescriptor)
            val outputFileStream = FileOutputStream(outputFile)
            
            inputStream.use { input ->
                outputFileStream.use { output ->
                    input.copyTo(output)
                }
            }
            parcelFileDescriptor.close()
            Toast.makeText(this, "Added to Sync queue: $fileName", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "Failed to queue file: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    // NSD Discovery Callbacks
    override fun onDeviceDiscovered(name: String, host: InetAddress, port: Int) {
        runOnUiThread {
            discoveredDevices[name] = Pair(host, port)
            updateDeviceListUI()
        }
    }

    override fun onDeviceRemoved(name: String) {
        runOnUiThread {
            discoveredDevices.remove(name)
            updateDeviceListUI()
        }
    }

    private fun updateDeviceListUI() {
        binding.llDevicesContainer.removeAllViews()

        val targetDir = File(getExternalFilesDir(null), "ToMac")
        val pendingFiles = targetDir.listFiles()?.filter { it.isFile } ?: emptyList()

        if (discoveredDevices.isEmpty() && pendingFiles.isEmpty()) {
            binding.llDevicesContainer.addView(binding.tvNoDevices)
            binding.tvStatusLabel.text = "AIRDROP SHARING ACTIVE"
            return
        }

        if (pendingFiles.isNotEmpty()) {
            binding.tvStatusLabel.text = "SYNCING FILES..."
        } else {
            binding.tvStatusLabel.text = "AIRDROP SHARING ACTIVE"
        }

        // 1. List resolved local Wi-Fi devices
        for ((name, target) in discoveredDevices) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                )
                setPadding(8)
                gravity = Gravity.CENTER_VERTICAL
            }

            val tvDeviceName = TextView(this).apply {
                text = "📱 $name"
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 14f
                typeface = android.graphics.Typeface.MONOSPACE
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }

            val btnSend = Button(this).apply {
                text = "SEND"
                backgroundTintList = android.content.res.ColorStateList.valueOf(0xFFFF0000.toInt())
                setTextColor(0xFFFFFFFF.toInt())
                typeface = android.graphics.Typeface.MONOSPACE
                textSize = 12f
                setOnClickListener {
                    selectedDeviceTarget = target
                    filePickerLauncher.launch("*/*")
                }
            }

            row.addView(tvDeviceName)
            row.addView(btnSend)
            binding.llDevicesContainer.addView(row)
        }

        // 2. List pending ADB files
        for (file in pendingFiles) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                )
                setPadding(8)
                gravity = Gravity.CENTER_VERTICAL
            }

            val tvFileName = TextView(this).apply {
                text = "📤 ${file.name} (${formatFileSize(file.length())}) [Pending ADB]"
                setTextColor(0xFF888888.toInt())
                textSize = 13f
                typeface = android.graphics.Typeface.MONOSPACE
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                )
            }

            row.addView(tvFileName)
            binding.llDevicesContainer.addView(row)
        }
    }

    private fun getFileFromUri(context: Context, uri: Uri): File {
        val parcelFileDescriptor = context.contentResolver.openFileDescriptor(uri, "r")
        val fileDescriptor = parcelFileDescriptor?.fileDescriptor ?: throw Exception("Null file descriptor")
        val inputStream = FileInputStream(fileDescriptor)
        
        val tempFile = File(context.cacheDir, getFileName(context, uri))
        val outputStream = FileOutputStream(tempFile)
        inputStream.copyTo(outputStream)
        
        inputStream.close()
        outputStream.close()
        parcelFileDescriptor.close()
        return tempFile
    }

    private fun getFileName(context: Context, uri: Uri): String {
        var name = "file.bin"
        val cursor = context.contentResolver.query(uri, null, null, null, null)
        cursor?.use {
            if (it.moveToFirst()) {
                val nameIndex = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex != -1) {
                    name = it.getString(nameIndex)
                }
            }
        }
        return name
    }

    private fun formatFileSize(size: Long): String {
        if (size <= 0) return "0 B"
        val units = arrayOf("B", "KB", "MB", "GB", "TB")
        val digitGroups = (Math.log10(size.toDouble()) / Math.log10(1024.toDouble())).toInt()
        return String.format("%.1f %s", size / Math.pow(1024.toDouble(), digitGroups.toDouble()), units[digitGroups])
    }

    private fun updateClipboardUI() {
        val clip = clipboard.primaryClip
        if (clip != null && clip.itemCount > 0) {
            val text = clip.getItemAt(0).text?.toString() ?: ""
            val display = if (text.length > 40) "${text.take(37)}..." else text
            binding.tvStatus.text = "Clipboard: $display"
        } else {
            binding.tvStatus.text = "Clipboard Empty"
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        nsdHelper.stop()
        FileTransferService.stopServer()
        handler.removeCallbacks(checkFolderRunnable)
        clipboard.removePrimaryClipChangedListener(clipboardListener)
    }
}
