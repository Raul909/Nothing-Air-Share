package com.nothing.airshare

import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Toast

class ClipboardReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val action = intent.action
        Log.d("ClipboardReceiver", "Received intent: $action")

        if ("clipper.set" == action) {
            val text = intent.getStringExtra("text")
            if (text != null) {
                val clip = ClipData.newPlainText("Nothing AirShare", text)
                clipboard.setPrimaryClip(clip)
                Toast.makeText(context, "Clipboard synced from Mac: $text", Toast.LENGTH_SHORT).show()
                setResult(0, "Text is copied into clipboard.", null)
                Log.d("ClipboardReceiver", "Clipboard set: $text")
            } else {
                setResult(1, "No text provided.", null)
            }
        } else if ("clipper.get" == action) {
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
        }
    }
}
