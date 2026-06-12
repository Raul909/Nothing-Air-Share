package com.nothing.airshare

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
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

    // Register a file picker launcher
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

        // 4. Manual Clipboard operations for testing
        binding.btnCopy.setOnClickListener {
            val text = binding.etInput.text.toString()
            if (text.isNotEmpty()) {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = ClipData.newPlainText("Nothing AirShare", text)
                clipboard.setPrimaryClip(clip)
                Toast.makeText(this, "Copied to Clipboard", Toast.LENGTH_SHORT).show()
            }
        }

        binding.btnPaste.setOnClickListener {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val clip = clipboard.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val text = clip.getItemAt(0).text
                binding.tvStatus.text = text
            } else {
                binding.tvStatus.text = "Clipboard Empty"
            }
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

        if (discoveredDevices.isEmpty()) {
            binding.llDevicesContainer.addView(binding.tvNoDevices)
            return
        }

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
                text = name
                textColor = 0xFFFFFFFF.toInt()
                textSize = 14f
                typeface = android.graphics.Typeface.MONOSPACE
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }

            val btnSend = Button(this).apply {
                text = "SEND"
                backgroundTintList = android.content.res.ColorStateList.valueOf(0xFFFF0000.toInt())
                textColor = 0xFFFFFFFF.toInt()
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
        return String.format("%.2f %s", size / Math.pow(1024.toDouble(), digitGroups.toDouble()), units[digitGroups])
    }

    override fun onDestroy() {
        super.onDestroy()
        nsdHelper.stop()
        FileTransferService.stopServer()
    }
}

// Extension properties for concise layout generation
private var TextView.textColor: Int
    get() = currentTextColor
    set(value) = setTextColor(value)

private var Button.textColor: Int
    get() = currentTextColor
    set(value) = setTextColor(value)
