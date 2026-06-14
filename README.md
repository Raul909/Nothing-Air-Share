# Nothing AirShare & Sync ⚪️⚫️

**Seamless file sharing and bidirectional clipboard sync between iOS, macOS, and Nothing OS—without custom iOS apps.**

This project bridges Nothing OS devices (Phone 1, 2, 2a, 2a Plus, CMF Phone 1, etc.) and the Apple ecosystem. It completely eliminates the need for an intermediate bridge or third-party cloud accounts by using a **single Android APK**, a **lightweight macOS menu bar popover daemon**, and Apple's **built-in AirDrop/Universal Clipboard APIs**.

[![Download APK](apk/download_btn.svg)](https://github.com/Raul909/Nothing-Air-Share/releases/download/v2.6.0/NothingAirShare.apk)

---

## ⚡️ Ecosystem Architecture

```
                           ┌──────────────────┐
                           │     MacBook       │
                           │  (Menu Bar ⚫️)    │
                           │  Custom Popover  │
                           │  unified_sync.py │
                           └────────┬─────────┘
                                    │
                 ┌──────────────────┼──────────────────┐
                 │                  │                   │
          Wireless ADB        Wi-Fi Direct       Apple Native
        (Background Sync)     (P2P Sockets)     (AirDrop + UC)
                 │                  │                   │
    ┌────────────▼───────┐          │       ┌───────────▼──────────┐
    │   Nothing Phone    │◄─────────┘       │   iPhone / iPad      │
    │                    │                  │                      │
    │  NothingAirShare   │                  │  No app required —   │
    │  Companion App     │                  │  uses native AirDrop │
    │  (APK v2.6.0)      │                  │  & Universal         │
    │                    │                  │  Clipboard           │
    └────────────────────┘                  └──────────────────────┘
```

**Three components, one seamless loop:**

| Component | What It Does |
|---|---|
| **Android APK** | Native clipboard listener, Share Sheet integration, P2P file sender, card-grid dashboard with trackpad & media remote, Find Phone ring receiver |
| **macOS Daemon** | Menu bar popover with premium Nothing OS dark/red styling, manages ADB stream, clipboard bridge, Bonjour discovery, TCP command/file server, AirDrop forwarder |
| **iOS** | Zero setup — Apple's native AirDrop and Universal Clipboard flow through the Mac automatically |

---

## 📲 Install the Android Companion App

### Option A — Direct Download (Recommended)
1. Download the APK to your phone:

   [![Download APK](apk/download_btn.svg)](https://github.com/Raul909/Nothing-Air-Share/releases/download/v2.6.0/NothingAirShare.apk)

2. Open the downloaded file on your Nothing Phone
3. Tap **Install** (you may need to allow "Install from unknown sources" for your browser)
4. Open **Nothing AirShare** once to activate background clipboard sync

### Option B — Install Over ADB from Mac
Once the Mac daemon is running and connected (see below):
1. Click the `⚫️` menu bar icon to open the popover
2. Select **Connect ADB** if not connected
3. Install the APK wirelessly — open it on your phone once

---

## 🖥️ Install the macOS Sync Daemon

### Prerequisites
- macOS 12 Monterey or later
- [Homebrew](https://brew.sh) installed
- Python 3.9+

### Step-by-Step Installation

**1. Install ADB (Android Debug Bridge)**
```bash
brew install android-platform-tools
```

**2. Clone this repository**
```bash
git clone https://github.com/Raul909/Nothing-Air-Share.git ~/Nothing-Air-Share
```

**3. Create a Python virtual environment and install dependencies**
```bash
cd ~/Nothing-Air-Share
python3 -m venv .venv && source .venv/bin/activate
pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-Accessibility pyobjc-framework-ApplicationServices watchdog Pillow
```

**4. Launch the daemon**
```bash
python3 unified_sync.py
```

A **Nothing Dot (`⚫️`)** will appear in your Mac's menu bar. Click it to open the Popover panel!

---

## 🔗 Connect Your Nothing Phone

### First-Time Pairing (One-Time Setup)

**On your Nothing Phone:**
1. Go to **Settings > About phone > Software info**
2. Tap **Build number** 7 times to enable Developer Options
3. Go to **Settings > System > Developer options**
4. Enable **Wireless Debugging** and tap into it
5. Tap **Pair device with pairing code** — note the `IP:Port` and 6-digit code shown

**On your Mac (Terminal):**
```bash
adb pair <IP>:<PORT>
# Replace <IP>:<PORT> with the address shown on your phone screen
# Enter the 6-digit pairing code when prompted
```

### Connecting (After Pairing)

1. Click the `⚫️` icon in your Mac's menu bar to open the Popover panel
2. Click the **Connect ADB** button at the bottom
3. Enter your phone's Wireless Debugging IP and port (shown on the Wireless Debugging screen)
4. The dot turns solid white and the panel status updates to **Connected** along with battery percentage and phone model

> **Tip:** The daemon remembers your last connection address and auto-reconnects on startup.

---

## 📖 How to Use

### 📋 Clipboard Sync
| Direction | How |
|---|---|
| **Mac → Phone** | Copy anything on your Mac (`Cmd+C`) — it's instantly pushed to your phone's clipboard. Alternatively, click the **Clipboard** card in the Mac Popover to force sync. |
| **Phone → Mac** | Copy text on your phone — it appears on your Mac clipboard within 1 second |
| **iPhone → Phone** | Copy on iPhone → Universal Clipboard syncs to Mac → Mac forwards to phone |
| **Clipboard History** | Click `⚫️` menu bar → View **Clipboard History** list in the popover → click any of the last 3 items to restore and push to phone |

### 📁 File Sharing
| Direction | How |
|---|---|
| **Mac → Phone** | Drag any file into `~/NothingDrop` on your Mac — it's automatically pushed to the phone. Or click **Send Files** in the popover to pick a file. |
| **Phone → Mac** | Tap **Share** on any file → choose **Nothing AirShare**, or open the app and tap **SEND FILES** |
| **Phone → Mac (P2P)** | Open app → see your Mac under **Nearby Devices** in the drawer → tap **SEND** → pick file |
| **Mac → Phone (P2P)** | Click `⚫️` → click **Send File** next to your phone under **Nearby Devices** → pick a file to send |
| **iPhone → Phone** | AirDrop a file from iPhone to Mac — the daemon auto-forwards it to your phone |
| **Phone → iPhone** | After receiving a file from phone, click the Popover and choose to AirDrop to iOS |

### 📱 Find My Phone
Click the **Find Phone** card on the Mac popover dashboard. This will send a wireless broadcast to your Nothing Phone and trigger your system alarm sound out loud at maximum volume for 15 seconds so you can locate it instantly!

### ⚙️ Command Control
Click the **Commands** card on the Mac popover dashboard. You can trigger predefined system actions on your Mac, such as:
- **Lock Screen**: Puts Mac display to sleep immediately.
- **Toggle Dark Mode**: OS-wide appearance shift.
- **Open Terminal**: Launches macOS Terminal app.
- **Take Screenshot**: Triggers the screen capture tool.
- **Put Mac to Sleep**: Sleeps the machine safely.

### 📁 Smart File Routing (Phone → Mac)
Files pulled from your phone are automatically sorted:
| File Type | Destination |
|---|---|
| Images (`.jpg`, `.png`, `.heic`, etc.) | `~/Pictures/NothingDrop/` |
| Documents (`.pdf`, `.docx`, `.txt`, etc.) | `~/Documents/NothingDrop/` |
| Everything else | `~/NothingDrop/` |

All received files are indexed by **Spotlight** — find them instantly with `Cmd+Space`.

### 📱 Companion App Features
| Card | What It Does |
|---|---|
| **SEND FILES** | Opens the file picker to send a file to your Mac via Wi-Fi P2P or ADB |
| **CLIPBOARD SYNC** | Expands an inline text field — type and tap **COPY TO SYNC** to push to Mac |
| **REMOTE INPUT** | Opens a full-screen trackpad — control your Mac's cursor wirelessly (Requires Accessibility permission on Mac) |
| **MEDIA REMOTE** | Control Mac media playback (Play/Pause, Next, Previous) wirelessly |
| **☰ Drawer** | Slide open to see discovered nearby devices, settings, and about info |

### 🌙 Focus Mode Sync
Toggle **Do Not Disturb** on your Mac → your Nothing Phone's DND / Zen Mode follows automatically.

---

## ⚙️ Keep It Running (Run on Mac Startup)

### Option A — LaunchAgent (Recommended)

This makes the daemon start automatically every time you log in and restart it if it crashes:

**Install:**
```bash
# Copy the LaunchAgent plist (edit paths if you cloned elsewhere)
cp ~/Nothing-Air-Share/com.nothing.clipboard-sync.plist ~/Library/LaunchAgents/

# Load it
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nothing.clipboard-sync.plist
```

That's it — the `⚫️` dot will appear in your menu bar on every login.

**Check logs:**
```bash
# Stdout log
cat /tmp/nothing_clipboard_sync.log

# Error log
cat /tmp/nothing_clipboard_sync.err
```

**Uninstall / Stop:**
```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.nothing.clipboard-sync.plist
rm ~/Library/LaunchAgents/com.nothing.clipboard-sync.plist
```

### Option B — Run Manually When Needed
```bash
cd ~/Nothing-Air-Share
source .venv/bin/activate
python3 unified_sync.py
```
Press `Ctrl+C` to stop. The `⚫️` dot disappears from the menu bar.

> **Why not a `.dmg`?**
> The macOS component uses `pyobjc` (Python-to-Cocoa bridge) and requires `adb` (Android platform tools). Bundling these into a standalone `.app` with PyInstaller/py2app produces a 200+ MB package that macOS Gatekeeper blocks without an Apple Developer Certificate ($99/yr for code-signing). The LaunchAgent approach is lighter, more transparent, and auto-updates when you `git pull`.

---

## 🖤 Tribute
This project is an unofficial tribute to the design language of [Nothing](https://nothing.tech). All rights to "Nothing", NDOT typography, and aesthetics belong to Nothing.
