package com.nothing.airshare

import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast

class ClipboardReceiver : BroadcastReceiver() {
    companion object {
        private var activeRingtone: Ringtone? = null

        /** Play the alarm for 15s. Called from the ADB broadcast and directly by
         *  [MacSession] (an in-app broadcast would need the receiver's permission). */
        fun ringPhone(context: Context) {
            val prefs = context.getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
            if (!prefs.getBoolean("pref_find_phone", true)) {
                Log.d("ClipboardReceiver", "Find Phone requested but disabled in settings.")
                return
            }
            try {
                activeRingtone?.let {
                    if (it.isPlaying) {
                        it.stop()
                    }
                }
                val notificationUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                    ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                val newRingtone = RingtoneManager.getRingtone(context, notificationUri)
                if (newRingtone != null) {
                    newRingtone.audioAttributes = AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                    newRingtone.play()
                    activeRingtone = newRingtone
                    Toast.makeText(context, "Finding Nothing Phone...", Toast.LENGTH_SHORT).show()
                    Log.d("ClipboardReceiver", "Find My Phone: Alarm playing")

                    // Stop after 15 seconds
                    Handler(Looper.getMainLooper()).postDelayed({
                        try {
                            if (newRingtone.isPlaying) {
                                newRingtone.stop()
                            }
                        } catch (e: Exception) {
                            Log.e("ClipboardReceiver", "Error stopping alarm: ${e.message}")
                        }
                    }, 15000)
                }
            } catch (e: Exception) {
                Log.e("ClipboardReceiver", "Error triggering Find My Phone alarm: ${e.message}")
            }
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        val prefs = context.getSharedPreferences("NothingAirSharePrefs", Context.MODE_PRIVATE)
        val isClipboardEnabled = prefs.getBoolean("pref_clipboard_sync", true)

        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val action = intent.action
        Log.d("ClipboardReceiver", "Received intent: $action")

        if ("clipper.set" == action) {
            if (!isClipboardEnabled) {
                Log.d("ClipboardReceiver", "Clipboard Sync is disabled in settings.")
                setResult(1, "Clipboard Sync is disabled in settings.", null)
                return
            }
            val text = intent.getStringExtra("text")
            if (text != null) {
                try {
                    val clip = ClipData.newPlainText("Nothing AirShare", text)
                    clipboard.setPrimaryClip(clip)
                } catch (e: SecurityException) {
                    Log.e("ClipboardReceiver", "SecurityException setting clipboard: ${e.message}")
                }
                val preview = if (text.length > 40) "${text.take(37)}..." else text
                Toast.makeText(context, "Clipboard synced from Mac: $preview", Toast.LENGTH_SHORT).show()
                setResult(0, "Text is copied into clipboard.", null)
                Log.d("ClipboardReceiver", "Clipboard set: $text")
            } else {
                setResult(1, "No text provided.", null)
            }
        } else if ("clipper.get" == action) {
            if (!isClipboardEnabled) {
                setResult(0, "", null)
                return
            }
            val clip = clipboard.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val text = clip.getItemAt(0).text?.toString() ?: ""
                val resultData = Bundle().apply {
                    putString("data", text)
                }
                setResult(-1, text, resultData)
                Log.d("ClipboardReceiver", "Clipboard get: $text")
            } else {
                setResult(0, "", null)
            }
        } else if ("clipper.ring" == action) {
            ringPhone(context)
        }
    }
}
