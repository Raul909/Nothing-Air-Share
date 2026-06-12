# Nothing AirShare & Sync ⚪️⚫️

**Seamless file sharing and bidirectional clipboard sync between iOS, macOS, and the Nothing Phone ecosystem.**

Built as a native, lightweight, and local-only alternative to AirDrop for users with a mixed Apple and Nothing ecosystem (Phone 1, 2, 2a, 2a Plus, CMF Phone 1, etc.).

---

## ⚡️ Features

- **Bidirectional Clipboard**: Copy text or links on macOS/iOS and paste on Nothing OS (and vice versa) instantly with zero-latency ADB streaming.
- **Smart File Drop**: Drag files into `~/NothingDrop` on macOS to send to the phone, or drop files into `/sdcard/Download/NothingDrop/ToMac/` on the phone to pull. Automatically routes pictures to `~/Pictures/NothingDrop` and documents to `~/Documents/NothingDrop`.
- **macOS Menu Bar App**: A native macOS status item showing phone connection status, battery percentage, and a history of the last 50 clipboard items.
- **Glyph Integration**: Triggers the Essential Glyph notification light on Nothing Phone when receiving data.
- **Focus Sync**: Synchronizes macOS Do Not Disturb with Android's system `zen_mode` in real-time.
- **iOS App**: A companion SwiftUI app designed with the signature Nothing OS aesthetic, supporting high-speed file streaming.

---

## 🚀 Quick Setup

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

### 3. Connect the Phone
1. A **Nothing Dot (`⚫️`)** will appear in your Mac's menu bar.
2. Pair your phone in Terminal using the pairing IP:Port from your phone's screen:
   ```bash
   adb pair [IP_ADDRESS:PORT]
   # Enter the 6-digit pairing code when prompted
   ```
3. Click the `⚫️` menu bar icon, select **Connect Wireless ADB...**, and enter your phone's active IP address and port (e.g. `192.168.1.100:5555`).
4. Once connected (`⚪️`), select **Install Nothing AirShare APK...** from the menu bar to install the companion Android app automatically. Open the app on your phone once to activate background sync.

---

## 📱 iOS App Setup
1. Open the `NothingApp` folder in **Xcode** on your macOS.
2. Download and add the **NDOT-45** font (`NDOT-45.ttf`) to the project.
3. Build and run on your iOS device. Grant **Local Network** permissions when prompted.

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
