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
import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.view.ViewConfiguration
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
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

    // Notification permission (Android 13+) — needed so the keep-alive foreground service
    // can show its ongoing notification. We (re)start the service once resolved.
    private val notifPermLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { _ ->
        SyncService.start(this)
    }

    // Register a file picker launcher for direct P2P transfer
    private val filePickerLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null && selectedDeviceTarget != null) {
            try {
                val target = selectedDeviceTarget!!
                // Stream file directly from URI instead of copying to cache (K3)
                FileTransferService.sendFileFromUri(this, uri, target.first, target.second)
            } catch (e: Exception) {
                Toast.makeText(this, "Failed to prepare file: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        // Apply theme before inflating views to avoid recreation flicker
        val initialPrefs = getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
        val startupTheme = initialPrefs.getString("pref_theme", "system") ?: "system"
        val nightMode = when (startupTheme) {
            "light" -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_NO
            "dark" -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_YES
            else -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
        }
        androidx.appcompat.app.AppCompatDelegate.setDefaultNightMode(nightMode)

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

        // 1. Ask for notification permission (Android 13+) so the foreground
        //    service notification is visible, then start the always-on sync service.
        ensureBackgroundPermissions()
        SyncService.start(this)

        // 2. Networking (NSD discovery, TCP server, duplex Mac session, clipboard &
        //    battery bridges) all live in SyncService now so sync survives the app
        //    being backgrounded. Observe its discovered-device set for the drawer UI.
        SyncService.devicesChanged = { runOnUiThread { updateDeviceListUI() } }
        MacSession.connectionListener = { connected ->
            runOnUiThread { binding.tvStatus.text = if (connected) "Connected to Mac" else "Searching for Mac..." }
        }

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
        val savedPin = prefs.getString("pref_security_pin", "1234") ?: "1234"
        val savedFontSize = prefs.getString("pref_font_size", "medium") ?: "medium"
        val savedTheme = prefs.getString("pref_theme", "system") ?: "system"
        
        binding.etMacIp.setText(savedMacIp)
        binding.etMacPort.setText(savedMacPort.toString())
        binding.etLocalPort.setText(savedLocalPort.toString())
        binding.etSecurityPin.setText(savedPin)
        FileTransferService.securityPin = savedPin
        binding.switchClipboardSync.isChecked = savedClipboardSync
        binding.switchFindPhone.isChecked = savedFindPhone
        binding.switchRemoteInput.isChecked = savedRemoteInput

        when (savedFontSize) {
            "small" -> binding.rbFontSmall.isChecked = true
            "large" -> binding.rbFontLarge.isChecked = true
            else -> binding.rbFontMedium.isChecked = true
        }
        applyFontSettings()

        when (savedTheme) {
            "light" -> binding.rbThemeLight.isChecked = true
            "dark" -> binding.rbThemeDark.isChecked = true
            else -> binding.rbThemeSystem.isChecked = true
        }

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
            val pin = binding.etSecurityPin.text.toString().trim()
            val clipboardSync = binding.switchClipboardSync.isChecked
            val findPhone = binding.switchFindPhone.isChecked
            val remoteInput = binding.switchRemoteInput.isChecked

            val fontSize = when (binding.rgFontSize.checkedRadioButtonId) {
                R.id.rbFontSmall -> "small"
                R.id.rbFontLarge -> "large"
                else -> "medium"
            }
            val selectedTheme = when (binding.rgTheme.checkedRadioButtonId) {
                R.id.rbThemeLight -> "light"
                R.id.rbThemeDark -> "dark"
                else -> "system"
            }

            prefs.edit().apply {
                putString("mac_ip", macIp)
                putInt("mac_port", macPort)
                putInt("local_port", localPort)
                putString("pref_security_pin", pin)
                putBoolean("pref_clipboard_sync", clipboardSync)
                putBoolean("pref_find_phone", findPhone)
                putBoolean("pref_remote_input", remoteInput)
                putString("pref_font_size", fontSize)
                putString("pref_theme", selectedTheme)
                apply()
            }
            FileTransferService.securityPin = pin
            applyFontSettings()

            val mode = when (selectedTheme) {
                "light" -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_NO
                "dark" -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_YES
                else -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
            }
            androidx.appcompat.app.AppCompatDelegate.setDefaultNightMode(mode)

            // Networking (server + NSD) lives in SyncService; restart it to apply
            // a local-port change (it re-reads the port from prefs on create).
            if (FileTransferService.port != localPort) {
                stopService(Intent(this, SyncService::class.java))
                SyncService.start(this)
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

        // --- Trackpad: full MacBook-style multi-touch gestures ---
        setupTrackpadGestures()

        // --- Media button handlers ---
        binding.btnPlayPause.setOnClickListener { MacSession.sendMediaKey("play_pause") }
        binding.btnPrev.setOnClickListener { MacSession.sendMediaKey("prev") }
        binding.btnNext.setOnClickListener { MacSession.sendMediaKey("next") }
        binding.btnVolDown.setOnClickListener { MacSession.sendMediaKey("vol_down") }
        binding.btnMute.setOnClickListener { MacSession.sendMediaKey("mute") }
        binding.btnVolUp.setOnClickListener { MacSession.sendMediaKey("vol_up") }

        // --- System Utilities (Wireless Debugging) ---
        binding.btnWirelessDebugging.setOnClickListener {
            try {
                startActivity(Intent("android.settings.WIFI_ADB_SETTINGS"))
            } catch (e: Exception) {
                try {
                    startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS))
                    Toast.makeText(this, "Wireless Debugging settings not found. Opening Developer Options.", Toast.LENGTH_LONG).show()
                } catch (ex: Exception) {
                    Toast.makeText(this, "Failed to open developer settings: ${ex.message}", Toast.LENGTH_SHORT).show()
                }
            }
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

    private fun updateDeviceListUI() {
        binding.llDevicesContainer.removeAllViews()

        val discoveredDevices = SyncService.discoveredDevices
        val targetDir = File(getExternalFilesDir(null), "ToMac")
        val pendingFiles = targetDir.listFiles()?.filter { it.isFile } ?: emptyList()

        if (discoveredDevices.isEmpty() && pendingFiles.isEmpty()) {
            // Detach first — tvNoDevices is a shared view and re-adding it while it
            // still has a parent throws IllegalStateException (this runs every 1s).
            (binding.tvNoDevices.parent as? android.view.ViewGroup)?.removeView(binding.tvNoDevices)
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

    private fun applyFontSettings() {
        val prefs = getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
        val fontSize = prefs.getString("pref_font_size", "medium") ?: "medium"
        val scale = when (fontSize) {
            "small" -> 0.90f
            "large" -> 1.20f
            else -> 1.00f
        }

        binding.tvTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 24f * scale)
        binding.tvSubtitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f * scale)
        binding.tvStatusLabel.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 18f * scale)
        binding.tvStatus.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f * scale)

        // Card titles — 15sp base
        binding.tvSendFilesTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 15f * scale)
        binding.tvClipboardTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 15f * scale)
        binding.tvRemoteInputTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 15f * scale)
        binding.tvCardMediaTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 15f * scale)

        // Card descriptions — 12sp base
        binding.tvSendFilesDesc.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 12f * scale)
        binding.tvClipboardDesc.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 12f * scale)
        binding.tvRemoteInputDesc.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 12f * scale)
        binding.tvCardMediaDesc.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 12f * scale)

        binding.tvDrawerTitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 28f * scale)
        binding.tvDrawerSubtitle.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f * scale)
        binding.tvDeviceName.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 12f * scale)
        binding.tvDevicesHeader.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 12f * scale)
        binding.tvNoDevices.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 13f * scale)
        binding.drawerSettings.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f * scale)
        binding.drawerAbout.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f * scale)
    }

    // ---------------------------------------------------------------------------------
    // Trackpad — MacBook-style multi-touch. Tap = left click, two-finger tap = right
    // click, two-finger drag = scroll, double-tap-then-drag = click-and-drag, all with
    // haptics. Pointer acceleration is applied on the Mac side so raw deltas stay small.
    // ---------------------------------------------------------------------------------

    private var pendingDx = 0f
    private var pendingDy = 0f
    private var pendingOpcode: Byte = 0x01
    private var flushScheduled = false
    private var lastDeltaSendTime = 0L
    private val COALESCE_MS = 12L

    private val vibrator: Vibrator? by lazy {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
            } else {
                @Suppress("DEPRECATION") getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            }
        } catch (e: Exception) { null }
    }

    private fun hapticTick(ms: Long = 12L) {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION") v.vibrate(ms)
            }
        } catch (_: Exception) {}
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun setupTrackpadGestures() {
        val touchSlop = ViewConfiguration.get(this).scaledTouchSlop
        val tapTimeout = 260L
        val doubleTapWindow = ViewConfiguration.getDoubleTapTimeout().toLong()

        var downX = 0f; var downY = 0f
        var lastX = 0f; var lastY = 0f
        var downTime = 0L
        var movedBeyondSlop = false

        var isTwoFinger = false
        var twoFingerLastX = 0f; var twoFingerLastY = 0f
        var twoFingerMoved = false

        var lastTapUpTime = 0L
        var lastTapUpX = 0f; var lastTapUpY = 0f
        var armedForDragTap = false
        var isDragging = false

        fun centroid(e: MotionEvent, axisX: Boolean): Float {
            var sum = 0f
            for (i in 0 until e.pointerCount) sum += if (axisX) e.getX(i) else e.getY(i)
            return sum / e.pointerCount
        }

        binding.trackpadSurface.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.x; downY = event.y
                    lastX = event.x; lastY = event.y
                    downTime = System.currentTimeMillis()
                    movedBeyondSlop = false
                    isTwoFinger = false
                    twoFingerMoved = false
                    armedForDragTap = (downTime - lastTapUpTime) <= doubleTapWindow &&
                        Math.hypot((event.x - lastTapUpX).toDouble(), (event.y - lastTapUpY).toDouble()) <= touchSlop * 3
                    binding.trackpadCursor.x = event.x - 12f
                    binding.trackpadCursor.y = event.y - 12f
                    binding.trackpadCursor.visibility = View.VISIBLE
                }

                MotionEvent.ACTION_POINTER_DOWN -> {
                    isTwoFinger = true
                    twoFingerMoved = false
                    twoFingerLastX = centroid(event, true)
                    twoFingerLastY = centroid(event, false)
                    binding.trackpadCursor.visibility = View.INVISIBLE
                    if (isDragging) { MacSession.sendMouseUp(); isDragging = false }
                }

                MotionEvent.ACTION_MOVE -> {
                    if (isTwoFinger && event.pointerCount >= 2) {
                        val cx = centroid(event, true); val cy = centroid(event, false)
                        val sdx = cx - twoFingerLastX; val sdy = cy - twoFingerLastY
                        twoFingerLastX = cx; twoFingerLastY = cy
                        if (Math.abs(sdx) > 0.5f || Math.abs(sdy) > 0.5f) {
                            if (Math.hypot((cx - downX).toDouble(), (cy - downY).toDouble()) > touchSlop) twoFingerMoved = true
                            queueDelta(0x02, sdx, sdy)
                        }
                    } else if (!isTwoFinger) {
                        val dx = event.x - lastX; val dy = event.y - lastY
                        lastX = event.x; lastY = event.y
                        if (!movedBeyondSlop &&
                            Math.hypot((event.x - downX).toDouble(), (event.y - downY).toDouble()) > touchSlop) {
                            movedBeyondSlop = true
                            if (armedForDragTap && !isDragging) {
                                MacSession.sendMouseDown(); isDragging = true; hapticTick(18)
                            }
                        }
                        if (movedBeyondSlop) queueDelta(0x01, dx, dy)
                        binding.trackpadCursor.x = event.x - 12f
                        binding.trackpadCursor.y = event.y - 12f
                    }
                }

                MotionEvent.ACTION_UP -> {
                    binding.trackpadCursor.visibility = View.INVISIBLE
                    handler.post { flushDeltaNow() }
                    val duration = System.currentTimeMillis() - downTime
                    if (isDragging) {
                        MacSession.sendMouseUp(); isDragging = false; hapticTick(14)
                    } else if (isTwoFinger) {
                        if (!twoFingerMoved && duration < tapTimeout) { MacSession.sendMouseRightClick(); hapticTick(16) }
                    } else if (!movedBeyondSlop && duration < tapTimeout) {
                        MacSession.sendMouseClick(); hapticTick(12)
                        lastTapUpTime = System.currentTimeMillis()
                        lastTapUpX = event.x; lastTapUpY = event.y
                    }
                    armedForDragTap = false
                }

                MotionEvent.ACTION_CANCEL -> {
                    binding.trackpadCursor.visibility = View.INVISIBLE
                    if (isDragging) { MacSession.sendMouseUp(); isDragging = false }
                    armedForDragTap = false
                }
            }
            true
        }
    }

    private fun queueDelta(opcode: Byte, dx: Float, dy: Float) {
        handler.post {
            if (pendingOpcode != opcode) {
                flushDeltaNow()
                pendingOpcode = opcode
            }
            pendingDx += dx
            pendingDy += dy
            if (!flushScheduled) {
                flushScheduled = true
                val now = System.currentTimeMillis()
                val wait = (COALESCE_MS - (now - lastDeltaSendTime)).coerceIn(0L, COALESCE_MS)
                handler.postDelayed({ flushDeltaNow() }, wait)
            }
        }
    }

    private fun flushDeltaNow() {
        flushScheduled = false
        val dx = pendingDx; val dy = pendingDy
        pendingDx = 0f; pendingDy = 0f
        if (dx == 0f && dy == 0f) return
        lastDeltaSendTime = System.currentTimeMillis()
        MacSession.sendDeltaBinary(pendingOpcode, dx, dy)
    }

    private fun ensureBackgroundPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        val prefs = getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("asked_batt_opt", false)) {
            prefs.edit().putBoolean("asked_batt_opt", true).apply()
            requestBatteryOptimizationExemption()
        }
    }

    private fun requestBatteryOptimizationExemption() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:\$packageName")
                })
            }
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "Battery optimization request failed: \${e.message}")
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacks(checkFolderRunnable)
        clipboard.removePrimaryClipChangedListener(clipboardListener)
        // Networking lives in SyncService and keeps running in the background;
        // just detach the UI callbacks so this Activity can be collected.
        SyncService.devicesChanged = null
        MacSession.connectionListener = null
    }
}
