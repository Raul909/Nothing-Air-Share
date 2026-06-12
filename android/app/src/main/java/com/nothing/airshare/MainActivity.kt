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
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.setPadding
import com.nothing.airshare.databinding.ActivityMainBinding
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var clipboard: ClipboardManager
    private val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
        updateClipboardUI()
    }

    private val handler = Handler(Looper.getMainLooper())
    private val checkFolderRunnable = object : Runnable {
        override fun run() {
            updatePendingFilesUI()
            handler.postDelayed(this, 1000)
        }
    }

    // Register a file picker launcher
    private val filePickerLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) {
            saveSharedFileToSyncFolder(uri)
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

        // Set up the device/files section header to show pending files
        binding.tvDevicesHeader.text = "PENDING OUTGOING FILES"

        // Replace the default "Scanning..." text to guide the user
        binding.tvNoDevices.text = "No files pending. Share files from any app via the Android Share sheet, or copy text to sync clipboards."

        // Add picker trigger to the container or title for manual file selection
        binding.llDevicesContainer.setOnClickListener {
            filePickerLauncher.launch("*/*")
        }

        // Add a click handler for the widget status to trigger file picker
        binding.widgetStatus.setOnClickListener {
            filePickerLauncher.launch("*/*")
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

        // Start polling the outgoing folder
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
            updatePendingFilesUI()
        } catch (e: Exception) {
            Toast.makeText(this, "Failed to queue file: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun updatePendingFilesUI() {
        val targetDir = File(getExternalFilesDir(null), "ToMac")
        val files = targetDir.listFiles()?.filter { it.isFile } ?: emptyList()

        binding.llDevicesContainer.removeAllViews()

        if (files.isEmpty()) {
            binding.llDevicesContainer.addView(binding.tvNoDevices)
            binding.tvStatusLabel.text = "AIRDROP SHARING ACTIVE"
            binding.tvStatus.text = "Tap here to send a file to Mac"
            return
        }

        binding.tvStatusLabel.text = "SYNCING FILES..."
        binding.tvStatus.text = "Waiting for Mac to pull ${files.size} file(s)"

        for (file in files) {
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
                text = "📤 ${file.name} (${formatFileSize(file.length())})"
                setTextColor(0xFFFFFFFF.toInt())
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
        handler.removeCallbacks(checkFolderRunnable)
        clipboard.removePrimaryClipChangedListener(clipboardListener)
    }
}
