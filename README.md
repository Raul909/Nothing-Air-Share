<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apk/icon_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="apk/icon.png">
    <img alt="Nothing AirShare Logo" src="apk/icon.png" width="96" height="96" />
  </picture>
</p>

# Nothing AirShare & Sync ⚪️⚫️

**Seamless file sharing and bidirectional clipboard sync between iOS, macOS, and Nothing OS—without custom iOS apps.**

*Featuring a custom, minimalist Nothing OS-inspired dot-matrix adaptive icon designed with transparency. It dynamically inverts between light and dark themes to fit perfectly in your browser or phone launcher! Showcasing open-source collaboration and creative interface design.*

[![Download Latest APK](apk/download_latest.svg?v=2.9.1)](https://github.com/Raul909/Nothing-Air-Share/releases/latest/download/NothingAirShare.apk)

<p align="center">
  <a href="https://github.com/Raul909/Nothing-Air-Share/releases/latest"><img alt="Latest Release" src="https://img.shields.io/github/v/release/Raul909/Nothing-Air-Share?style=for-the-badge&color=e60012&label=latest"></a>
  <img alt="Downloads" src="https://img.shields.io/github/downloads/Raul909/Nothing-Air-Share/total?style=for-the-badge&color=000000&label=downloads">
  <img alt="Platform" src="https://img.shields.io/badge/for-Nothing%20OS%20%C2%B7%20macOS%20%C2%B7%20iOS-000000?style=for-the-badge">
  <a href="https://github.com/Raul909/Nothing-Air-Share/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/Raul909/Nothing-Air-Share?style=for-the-badge&color=e60012"></a>
</p>

---

## ✨ Why Nothing AirShare?

Apple keeps AirDrop and Universal Clipboard locked to Apple devices — so your **Nothing Phone** gets left out. Nothing AirShare bridges that gap by using your Mac as a quiet relay: **nothing to install on your iPhone**, a lightweight companion app on your Nothing Phone, and everything running **locally over your own Wi‑Fi** — no cloud, no account, no telemetry.

- 🍎🤝⚫️ **Bridges Apple ↔ Nothing** — reuses native AirDrop + Universal Clipboard; zero setup on iOS
- 📋 **Instant two‑way clipboard** — copy on your Mac, paste on your phone (and back) — text *and* images
- 📁 **Effortless file sharing** — drag into a folder or use the Share Sheet; files auto‑sort into Pictures / Documents / Downloads
- 🖱️ **Phone as a trackpad + media remote** — steer your Mac's cursor and playback wirelessly
- 🔔 **Find My Phone**, 🌙 **Focus / DND sync**, and 🔋 **live battery** right in the menu bar
- 🔒 **Private by design** — 100% local, PIN‑protected transfers, fully open source
- ⚫️ **Premium Nothing OS aesthetic** — a dot‑matrix menu‑bar app with a custom adaptive icon

> New here? Jump straight to **[Install the Android app](#-install-the-android-companion-app)** and **[Install the macOS daemon](#️-install-the-macos-sync-daemon)**.

---

## ⚡️ Ecosystem Architecture

```
                           ┌──────────────────┐
                           │     MacBook       │
                           │  (Menu Bar ⚫️)    │
                           │  Custom Popover  │
                           │  unified_sync.py │
                           └─────────┬────────┘
                                     │
                 ┌───────────────────┼──────────────────┐
                 │                   │                  │
          Wireless ADB         Wi-Fi Direct       Apple Native
        (Background Sync)      (P2P Sockets)     (AirDrop + UC)
                 │                   │                  │
    ┌────────────▼───────┐           │       ┌───────────▼──────────┐
    │   Nothing Phone    │◄──────────┘       │   iPhone / iPad      │
    │                    │                   │                      │
    │  NothingAirShare   │                   │  No app required —   │
    │  Companion App     │                   │  uses native AirDrop │
    │  (APK v2.9.1)      │                   │  & Universal         │
    │                    │                   │  Clipboard           │
    └────────────────────┘                   └──────────────────────┘
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
1. Download the latest version to your phone:

   [![Download Latest APK](apk/download_latest.svg?v=2.9.1)](https://github.com/Raul909/Nothing-Air-Share/releases/latest/download/NothingAirShare.apk)

   **Previous Version:**
   [![v2.9.1](apk/version_v2.9.1.svg?v=2.9.1)](https://github.com/Raul909/Nothing-Air-Share/releases/download/v2.9.1/NothingAirShare.apk)

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
- [Homebrew](https://brew.sh) installed (The setup script will install it for you if missing)

### One-Click Installation

For the simplest experience, we provide an automated setup script that compiles the python daemon into a native macOS Application (`.app`).

1. **Clone or Download this repository** to your Mac.
2. Open the folder and **double-click `setup_mac.command`**.
   *(Note: The first time, you may need to right-click -> Open -> Open, since it's an unverified script from the internet).*
3. The script will automatically install dependencies and bundle the app.
4. Once finished, **Nothing AirShare.app** will be installed in your `/Applications` folder!

You can now launch it anytime from Launchpad or Finder. A **Nothing Dot (`⚫️`)** will appear in your Mac's menu bar. Click it to open the Popover panel!

---

## 🔗 Connect Your Nothing Phone

### First-Time Pairing (One-Time Setup)

**On your Nothing Phone:**
1. Go to **Settings > System > Developer options** (If you don't see it, go to *About phone > Software info* and tap *Build number* 7 times to enable it).
2. Enable **Wireless Debugging** and tap into it.
3. Tap **Pair device with pairing code** — note the `IP:Port` (e.g. `192.168.x.x:4XXXX`) and the 6-digit Wi-Fi pairing code.

**On your Mac (Visual App Flow):**
1. Click the `⚫️` menu bar icon -> click **Connect ADB** at the bottom.
2. Select **Pair Device**.
3. Enter the `IP:Port` and the 6-digit pairing code shown on your phone, then click **Pair**.
4. Once successfully paired, a notification will appear, and you can connect!

*(Alternatively, you can run `adb pair <IP>:<PORT>` in your Mac Terminal and enter the code there).*

### Connecting & Handshake (After Pairing)

Once paired, connecting is fully automated:
1. Turn on **Wireless Debugging** on your Nothing Phone.
2. Within seconds, the Mac app will automatically discover your phone's connection port and run `adb connect` in the background.
3. The menu bar dot will turn solid white (`⚪️`), and the Popover panel will show **Connected**.

*If automatic connection does not trigger, you can connect manually:*
- Click `⚫️` -> click **Connect ADB** -> select **Connect** -> enter your phone's Wireless Debugging `IP:Port` (shown on the main Wireless Debugging screen).

---

## 📖 How to Use

### 📋 Clipboard Sync
| Direction | How |
|---|---|
| **Mac → Phone** | Copy anything on your Mac (`Cmd+C`) — it's instantly pushed to your phone's clipboard. Alternatively, click the **Clipboard** card in the Mac Popover to force sync. |
| **Phone → Mac** | Copy text on your phone — it appears on your Mac clipboard within ~600ms |
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
| **REMOTE INPUT** | Opens a full-screen trackpad with **Multi-Touch Gestures**: <br>• 1-Finger Tap: Left Click <br>• 2-Finger Tap: Right Click <br>• 2-Finger Swipe Left/Right: Browser Back/Forward <br>• 3-Finger Swipe Up/Down: Mission Control / App Exposé <br>• 3-Finger Swipe Left/Right: Change Desktop Spaces |
| **MEDIA REMOTE** | Control Mac media playback (Play/Pause, Next, Previous) wirelessly |
| **☰ Drawer** | Slide open to see discovered nearby devices, settings, and about info |
| **⚙ Settings Overlay** | Customize options including: <br>• **Font Size Scaling**: Toggle SMALL, MEDIUM (default), or LARGE font scaling sizes globally in real-time. <br>• **⚙ Wireless Debugging Button**: Launches Android system Wireless Debugging / developer options panel. |

### 🌙 Focus Mode Sync
Toggle **Do Not Disturb** on your Mac → your Nothing Phone's DND / Zen Mode follows automatically.

---

## ⚙️ Keep It Running (Run on Mac Startup)

Since Nothing AirShare is now a native `.app`, setting it to run at login is incredibly simple!

**To launch automatically on startup:**
1. Open **System Settings** on your Mac.
2. Navigate to **General > Login Items**.
3. Click the `+` button under "Open at Login".
4. Select **Nothing AirShare.app** from your `/Applications` folder.

That's it — the `⚫️` dot will quietly appear in your menu bar every time you turn on your Mac.

---

## 📋 Changelog

### v2.9.1 — Remote Gestures & Media Fixes
**Multi-Touch Gestures**
- Trackpad now supports 2-finger horizontal swipes for **Browser Back/Forward**.
- Added 3-finger swipe gestures for **Mission Control, App Exposé, and Space Switching**.
- Fixed macOS media keys (Play/Pause/Volume) not registering on modern macOS versions.
- Fixed "Find Phone" alert missing in the new TCP transport.

### v2.9.1 — Unified Transport & Native macOS App

**Native macOS Experience**
- Bundled the Python daemon into a native standalone `Nothing AirShare.app` using PyInstaller.
- App runs natively in the background (Menu Bar Accessory mode) with no Terminal required.
- Easy 1-click installation via `setup_mac.command`.

### v2.8.0 — Connection Stability, Menu Bar Sync & Latency Optimization

**Connection Stability**
- Fixed random socket drops caused by incomplete `recv()` reads — added reliable `recv_exact()` helper
- Android command socket (trackpad/media) now auto-reconnects with exponential backoff (3 retries)
- Added connection state lock to prevent race conditions between Bonjour auto-discovery and ADB monitor
- File transfer timeout now scales dynamically with file size (no more timeouts on large files)
- Android TCP server retries binding with backoff if port is occupied
- Socket errors are now surfaced to the Android UI with automatic reconnection

**Menu Bar Popover**
- Popover now auto-refreshes every 2 seconds while open (clipboard history, devices, battery update live)
- Clipboard history shows 3 items (was 2) — matches documentation
- Nearby devices shows up to 3 (was 2)
- Fixed memory leak from button maps growing without bound on each refresh
- Battery display no longer flickers from duplicate updates

**Latency Optimization**
- Phone→Mac clipboard sync reduced from ~2s to ~600ms (3.3× faster)
- Trackpad input uses binary protocol (9 bytes vs ~50 bytes JSON) with 16ms move coalescing for ~60fps
- `TCP_NODELAY` enabled on Mac TCP server — eliminates up to 200ms Nagle buffering
- File transfer buffers increased from 64KB to 256KB for better Wi-Fi throughput
- Removed redundant `dumpsys battery` ADB polling — uses real-time Android TCP broadcasts only
- Battery broadcasts debounced to 30s intervals to prevent socket storms
- Files sent from Android now stream directly from URI without cache copy (saves memory + storage)

---

## 🖤 Tribute
This project is an unofficial tribute to the design language of [Nothing](https://nothing.tech). All rights to "Nothing", NDOT typography, and aesthetics belong to Nothing.
