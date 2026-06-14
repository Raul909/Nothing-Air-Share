package com.nothing.airshare

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.res.ResourcesCompat
import androidx.core.view.GravityCompat
import androidx.core.view.setPadding
import androidx.drawerlayout.widget.DrawerLayout
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
    private var isClipboardExpanded = false
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

        // Initialize settings
        val prefs = getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
        val savedLocalPort = prefs.getInt("local_port", 53317)
        FileTransferService.port = savedLocalPort

        // Handle incoming share intents
        handleSendIntent(intent)

        // 1. Initialize NSD Bonjour Discovery & Advertising
        nsdHelper = NsdHelper(this, this)
        nsdHelper.registerService(savedLocalPort)
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

        // --- Drawer setup ---
        val drawerLayout = binding.root
        binding.btnMenu.setOnClickListener {
            drawerLayout.openDrawer(GravityCompat.START)
        }

        // Set device name in drawer header
        binding.tvDeviceName.text = Build.MODEL

        // Load settings values into inputs
        val savedMacIp = prefs.getString("mac_ip", "") ?: ""
        val savedMacPort = prefs.getInt("mac_port", 53318)
        val savedClipboardSync = prefs.getBoolean("pref_clipboard_sync", true)
        val savedFindPhone = prefs.getBoolean("pref_find_phone", true)
        val savedRemoteInput = prefs.getBoolean("pref_remote_input", true)
        
        binding.etMacIp.setText(savedMacIp)
        binding.etMacPort.setText(savedMacPort.toString())
        binding.etLocalPort.setText(savedLocalPort.toString())
        binding.switchClipboardSync.isChecked = savedClipboardSync
        binding.switchFindPhone.isChecked = savedFindPhone
        binding.switchRemoteInput.isChecked = savedRemoteInput

        // Drawer click handlers
        binding.drawerSettings.setOnClickListener {
            drawerLayout.closeDrawer(GravityCompat.START)
            binding.overlaySettings.visibility = View.VISIBLE
        }

        binding.drawerAbout.setOnClickListener {
            drawerLayout.closeDrawer(GravityCompat.START)
            binding.overlayAbout.visibility = View.VISIBLE
        }

        // --- Settings Overlay Handlers ---
        binding.btnBackSettings.setOnClickListener {
            binding.overlaySettings.visibility = View.GONE
        }

        binding.btnSaveSettings.setOnClickListener {
            val macIp = binding.etMacIp.text.toString().trim()
            val macPortStr = binding.etMacPort.text.toString().trim()
            val localPortStr = binding.etLocalPort.text.toString().trim()

            val macPort = macPortStr.toIntOrNull() ?: 53318
            val localPort = localPortStr.toIntOrNull() ?: 53317
            val clipboardSync = binding.switchClipboardSync.isChecked
            val findPhone = binding.switchFindPhone.isChecked
            val remoteInput = binding.switchRemoteInput.isChecked

            prefs.edit().apply {
                putString("mac_ip", macIp)
                putInt("mac_port", macPort)
                putInt("local_port", localPort)
                putBoolean("pref_clipboard_sync", clipboardSync)
                putBoolean("pref_find_phone", findPhone)
                putBoolean("pref_remote_input", remoteInput)
                apply()
            }

            // Update local server port and restart server if local port changed
            if (FileTransferService.port != localPort) {
                FileTransferService.stopServer()
                FileTransferService.port = localPort
                FileTransferService.startServer()
                
                // Re-register NSD service with new port
                nsdHelper.stop()
                nsdHelper.registerService(localPort)
                nsdHelper.discoverServices()
            }

            Toast.makeText(this, "Settings Saved Successfully", Toast.LENGTH_SHORT).show()
            binding.overlaySettings.visibility = View.GONE
        }

        // --- About Overlay Handlers ---
        binding.btnBackAbout.setOnClickListener {
            binding.overlayAbout.visibility = View.GONE
        }

        // --- Card click handlers ---
        binding.cardSendFiles.setOnClickListener {
            selectedDeviceTarget?.let {
                filePickerLauncher.launch("*/*")
            } ?: run {
                // No device selected — open file picker anyway for ADB queue
                filePickerLauncher.launch("*/*")
            }
        }

        binding.cardClipboard.setOnClickListener {
            val enabled = prefs.getBoolean("pref_clipboard_sync", true)
            if (!enabled) {
                Toast.makeText(this, "Clipboard Sync plugin is disabled in Settings", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            isClipboardExpanded = !isClipboardExpanded
            binding.panelClipboard.visibility = if (isClipboardExpanded) View.VISIBLE else View.GONE
            binding.cardClipboard.background = getDrawable(
                if (isClipboardExpanded) R.drawable.card_bg_active else R.drawable.card_bg
            )
        }

        binding.cardRemoteInput.setOnClickListener {
            val enabled = prefs.getBoolean("pref_remote_input", true)
            if (enabled) {
                binding.overlayTrackpad.visibility = View.VISIBLE
            } else {
                Toast.makeText(this, "Remote Trackpad plugin is disabled in Settings", Toast.LENGTH_SHORT).show()
            }
        }

        binding.cardMedia.setOnClickListener {
            binding.overlayMedia.visibility = View.VISIBLE
        }

        // --- Overlay back buttons ---
        binding.btnBackTrackpad.setOnClickListener {
            binding.overlayTrackpad.visibility = View.GONE
        }

        binding.btnBackMedia.setOnClickListener {
            binding.overlayMedia.visibility = View.GONE
        }

        // --- Trackpad touch handling ---
        binding.trackpadSurface.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                    // Visual feedback: update a cursor dot position
                    binding.trackpadCursor.x = event.x - 12f
                    binding.trackpadCursor.y = event.y - 12f
                    binding.trackpadCursor.visibility = View.VISIBLE
                }
                MotionEvent.ACTION_UP -> {
                    binding.trackpadCursor.visibility = View.INVISIBLE
                }
            }
            true
        }

        // --- Media button placeholders ---
        binding.btnPlayPause.setOnClickListener {
            Toast.makeText(this, "Media control: awaiting Mac connection", Toast.LENGTH_SHORT).show()
        }
        binding.btnPrev.setOnClickListener {
            Toast.makeText(this, "Previous track: awaiting Mac connection", Toast.LENGTH_SHORT).show()
        }
        binding.btnNext.setOnClickListener {
            Toast.makeText(this, "Next track: awaiting Mac connection", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleSendIntent(intent)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        val drawerLayout = binding.root
        when {
            binding.overlayTrackpad.visibility == View.VISIBLE -> {
                binding.overlayTrackpad.visibility = View.GONE
            }
            binding.overlayMedia.visibility == View.VISIBLE -> {
                binding.overlayMedia.visibility = View.GONE
            }
            binding.overlaySettings.visibility == View.VISIBLE -> {
                binding.overlaySettings.visibility = View.GONE
            }
            binding.overlayAbout.visibility == View.VISIBLE -> {
                binding.overlayAbout.visibility = View.GONE
            }
            drawerLayout.isDrawerOpen(GravityCompat.START) -> {
                drawerLayout.closeDrawer(GravityCompat.START)
            }
            else -> super.onBackPressed()
        }
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
                typeface = ResourcesCompat.getFont(this@MainActivity, R.font.letteramono)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }

            val btnSend = Button(this).apply {
                text = "SEND"
                backgroundTintList = android.content.res.ColorStateList.valueOf(getColor(R.color.nothing_red))
                setTextColor(0xFFFFFFFF.toInt())
                typeface = ResourcesCompat.getFont(this@MainActivity, R.font.ndot57)
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
                typeface = ResourcesCompat.getFont(this@MainActivity, R.font.letteramono)
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
