# Nothing AirShare & Sync ⚪️⚫️

**Seamless file sharing and bidirectional clipboard sync between iOS, macOS, and the Nothing Phone ecosystem.**

Built as a native, lightweight, and local-only alternative to AirDrop for users with a mixed Apple and Nothing ecosystem (Phone 1, 2, 2a, 2a Plus, CMF Phone 1, etc.).

📦 **[Download NothingAirShare.apk (v2.5.0)](apk/NothingAirShare.apk)**

---

## ⚡️ Features

- **Bidirectional Clipboard**: Copy text or links on macOS/iOS and paste on Nothing OS (and vice versa) instantly with zero-latency ADB streaming.
- **Smart File Drop**: Drag files into `~/NothingDrop` on macOS to send to the phone, or drop files into `/sdcard/Download/NothingDrop/ToMac/` on the phone to pull. Automatically routes pictures to `~/Pictures/NothingDrop` and documents to `~/Documents/NothingDrop`.
- **macOS Menu Bar App**: A native macOS status item showing phone connection status, battery percentage, and a history of the last 50 clipboard items.
- **Glyph Integration**: Triggers the Essential Glyph notification light on Nothing Phone when receiving data.
- **Focus Sync**: Synchronizes macOS Do Not Disturb with Android's system `zen_mode` in real-time.
- **iOS App**: A companion SwiftUI app designed with the signature Nothing OS aesthetic, supporting high-speed file streaming.

---

## 🚀 Quick Setup (macOS & Android)

### 1. Prepare Your Nothing Phone
1. Connect your phone and Mac to the **same Wi-Fi network**.
2. Go to **Settings > About phone > Software info** and tap **Build number** 7 times to unlock developer options.
3. Go to **Settings > System > Developer options**, enable **Wireless Debugging**, and tap it to open the submenu.
4. Tap **Pair device with pairing code**. Keep this screen open (note the IP:Port and 6-digit code).

### 2. Install & Run on macOS
Open **Terminal** on your Mac and run the following commands to install dependencies, clone, and start the sync daemon:

```bash
# 1. Install ADB (if not already installed)
brew install android-platform-tools

# 2. Clone and start the app
git clone https://github.com/Raul909/Nothing-Air-Share.git ~/Nothing-Air-Share
cd ~/Nothing-Air-Share
python3 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Cocoa watchdog Pillow
python3 unified_sync.py
```

### 3. Connect & Pair
1. A **Nothing Dot (`⚫️`)** will appear in your Mac's menu bar.
2. Pair your phone in Terminal using the pairing IP:Port from your phone's screen:
   ```bash
   adb pair [IP_ADDRESS:PORT]
   # Enter the 6-digit pairing code when prompted
   ```
3. Click the `⚫️` menu bar icon, select **Connect Wireless ADB...**, and enter your phone's active IP address and port (e.g. `192.168.1.100:5555`).
4. Once connected (`⚪️`), the menu bar icon will show your phone's battery percentage and charging state.

---

## 📲 APK Installation Guide

To enable full bidirectional clipboard sync (bypassing background restrictions on Android 10+), install the companion Android app:

* **Option A: Automated Install (Easiest)**:
  Once the Mac status bar menu shows a connected status (`⚪️`), click the menu icon and choose **"Install Nothing AirShare APK..."**. It will automatically push and install the APK wirelessly via ADB.
* **Option B: Manual Sideload**:
  1. Download [NothingAirShare.apk](apk/NothingAirShare.apk) directly from this repository to your Nothing Phone.
  2. Open the downloaded `.apk` file using any file manager on your phone.
  3. If prompted, enable **"Install from Unknown Sources"** for the file manager, then tap **Install**.
  4. Open the installed **Nothing AirShare** app on your phone once to activate permissions.

Once the APK is installed and the Mac is connected, the app will show **"Connected"** on its screen, indicating the sync bridge is fully operational.

---

## 🔄 The USP: Seamless Android, macOS & iOS Integration

No intermediate websites, cloud servers, or messaging apps. The bridge is completely local, private, and automatic.

### 📋 Bidirectional Clipboard Sync
- **Mac ➔ Android**: Press `Cmd + C` to copy text, links, or images on Mac. Long-press and tap **Paste** on your Nothing Phone to paste immediately.
- **Android ➔ Mac**: Copy any text or link on your Nothing Phone. Press `Cmd + V` on your Mac to paste it instantly.
- **Clipboard History**: Click the `⚪️` menu bar icon on your Mac and hover over **Clipboard History** to see and select from your last 50 clipboard items.

### 📁 Smart File Drop (NothingDrop)
- **Mac ➔ Android**: Drag and drop any file into the `~/NothingDrop` folder on your Mac. It is instantly pushed to your phone's `Download/NothingDrop/` directory, and your phone will flash its Essential Glyph light.
- **Android ➔ Mac**: Save or copy any file on your phone into the `/sdcard/Download/NothingDrop/ToMac/` directory. Your Mac will instantly pull the file, delete the phone's temporary copy to save storage, and route it:
  - **Images & Screenshots** go to `~/Pictures/NothingDrop/`.
  - **Documents** (`.pdf`, `.docx`, `.txt`) go to `~/Documents/NothingDrop/`.
  - **All other files** go to `~/NothingDrop/`.
  - Pushed files are indexed in real-time for instant searching via Spotlight (`Cmd + Space`).

### 📱 iOS ➔ Mac & Android Sharing
1. Open the `NothingApp` folder in **Xcode** on your macOS.
2. Add the **NDOT-45** font (`NDOT-45.ttf`) to the project, build, and run on your iOS device.
3. Ensure both devices are on the same Wi-Fi network. The iOS app will discover nearby Mac or Nothing Phone peers automatically. Select any file and stream it at maximum speed.

### 🌙 Focus Mode Sync
- Toggle **Do Not Disturb** on your Mac. Your Nothing Phone will automatically turn on Do Not Disturb / Zen Mode. Turning it off on Mac restores the phone to normal.

---

## ⚙️ Run on Startup (macOS)
To run the sync service automatically in the background on login:
```bash
cp com.nothing.clipboard-sync.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nothing.clipboard-sync.plist
```

To stop:
```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.nothing.clipboard-sync.plist
```

---

## 🖤 Tribute
This project is an unofficial tribute to the design language of [Nothing](https://nothing.tech). All rights to "Nothing", NDOT typography, and aesthetics belong to Nothing.
