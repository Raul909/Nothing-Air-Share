# Nothing AirShare & Sync ⚪️⚫️

**Seamless file sharing and bidirectional clipboard sync between iOS, macOS, and Nothing OS—without custom iOS apps.**

This project bridges Nothing OS devices (Phone 1, 2, 2a, 2a Plus, CMF Phone 1, etc.) and the Apple ecosystem. It completely eliminates the need for an intermediate bridge or third-party cloud accounts by using a **single Android APK**, a **lightweight macOS menu bar daemon**, and Apple's **built-in AirDrop/Universal Clipboard APIs**.

📦 **[Download NothingAirShare.apk (v2.5.0)](apk/NothingAirShare.apk)**

---

## ⚡️ Ecosystem Architecture (How It Works)

```
   [ Nothing Phone ]                 [ MacBook ]                    [ iPhone / iPad ]
           │                              │                                 │
           │ ─── Wireless ADB Sync ─────► │ ◄─── Native Apple AirDrop ───── │  (File Transfer)
           │      (Background Stream)     │                                 │
           │                              │ ◄─── Universal Clipboard ────── │  (Clipboard Sync)
```

1. **Android**: A single background APK (`NothingAirShare.apk`) that acts as a native clipboard listener and integrates into the Android Share Sheet.
2. **macOS**: A menu bar status item (`unified_sync.py`) running in the background. It manages ADB communication with the phone, monitors clipboard pasteboards, and forwards files.
3. **iOS**: No custom apps required. Uses Apple's native **AirDrop** and **Universal Clipboard** to send/receive files and clipboards via the Mac.

---

## 🚀 Quick Setup

### 1. Prepare Your Nothing Phone
1. Connect your phone and Mac to the **same Wi-Fi network**.
2. Go to **Settings > About phone > Software info** and tap **Build number** 7 times.
3. Go to **Settings > System > Developer options**, enable **Wireless Debugging**, and tap it to open the submenu.
4. Tap **Pair device with pairing code** (keep this screen open showing the IP:Port and 6-digit code).

### 2. Install & Run on macOS
Open **Terminal** on your Mac and run:
```bash
# 1. Install ADB (if not already installed)
brew install android-platform-tools

# 2. Clone the repository and install requirements
git clone https://github.com/Raul909/Nothing-Air-Share.git ~/Nothing-Air-Share
cd ~/Nothing-Air-Share
python3 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Cocoa watchdog Pillow
python3 unified_sync.py
```

### 3. Connect & Pair
1. A **Nothing Dot (`⚫️`)** will appear in your Mac's menu bar.
2. Pair your phone in Terminal using the IP:Port from your phone's screen:
   ```bash
   adb pair [IP_ADDRESS:PORT]
   # Enter the 6-digit pairing code when prompted
   ```
3. Click the `⚫️` menu bar icon, select **Connect Wireless ADB...**, and enter your phone's active Wireless Debugging IP and port (e.g., `192.168.1.100:5555`).
4. Once connected (`⚪️`), select **Install Nothing AirShare APK...** from the menu bar to install the companion Android app automatically. Open the app on your phone once to activate sync.

---

## 🔄 The Features (In Action)

### 📋 Seamless Clipboard Synchronization
- **Mac ➔ Nothing Phone**: Copy any text or link on your Mac (`Cmd+C`). It is instantly pushed and written to your phone's system clipboard in the background.
- **Nothing Phone ➔ Mac**: Copy text on your phone. It is immediately synced to your Mac's system clipboard (press `Cmd+V` to paste).
- **iPhone ➔ Nothing Phone (and vice-versa)**: By utilizing Apple's built-in **Universal Clipboard**, copying text on your iPhone automatically populates the Mac clipboard, which is then instantly forwarded to your Nothing Phone (and vice-versa).
- **Clipboard History**: Click the macOS status bar dot and hover over **Clipboard History** to restore any of the last 50 clipboard items.

### 📁 Direct File Sharing (Zero-Config)
- **Mac ➔ Nothing Phone**: Drag and drop any file into the `~/NothingDrop` folder on your Mac. It is automatically pushed to your phone's `Download/NothingDrop/` directory and triggers an Essential Glyph light flash.
- **Nothing Phone ➔ Mac**: Tap **Share** on any photo, video, or file on your phone, and choose **Nothing AirShare** (or pick a file inside the app). The file is immediately pulled to your Mac, deleted from the phone to save space, and routed:
  - Images/Screenshots go to `~/Pictures/NothingDrop/`
  - Documents (.pdf, .txt, etc.) go to `~/Documents/NothingDrop/`
  - Other files go to `~/NothingDrop/`
  - All pulled files are indexed instantly for macOS Spotlight search (`Cmd+Space`).
- **iPhone ➔ Nothing Phone**: AirDrop any file natively from your iPhone to your Mac. The Mac daemon watches the `~/Downloads` directory for AirDropped files and automatically forwards them to the Nothing Phone over ADB.
- **Nothing Phone ➔ iPhone**: When a file is pulled from your phone, the Mac menu bar icon updates with a new action: **"AirDrop '[filename]' to iOS..."**. Clicking it immediately opens macOS's native AirDrop share sheet, allowing you to send it to your iPhone with a single click.

### 🌙 Focus Mode Synchronization
- Toggle **Do Not Disturb** on your Mac. Your Nothing Phone will automatically turn on Do Not Disturb / Zen Mode. Turning it off restores the phone to normal.

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
