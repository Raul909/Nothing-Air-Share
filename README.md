# Nothing AirShare & Sync ⚪️⚫️

**Bridging the gap between iOS, macOS, and Nothing OS.**

Let's be honest: AirDrop is the only thing keeping many of us on iPhone. But the Nothing Phone (2a), (2), and (1) have an aesthetic that's just... *chef's kiss*. 

I built this project because I wanted the best of both worlds. I wanted my Nothing Phone to feel like it belonged in my Apple ecosystem without the "wall" getting in the way. This is a suite of tools designed to make file sharing and clipboard syncing between Mac, iOS, and Nothing Phone feel native, fast, and—most importantly—beautifully minimal.

---

## 💠 The Philosophy
No bloat. No accounts. No cloud servers. Just your devices talking to each other over your local Wi-Fi, wrapped in that signature Nothing dot-matrix aesthetic.

## 🚀 Features

### 1. Nothing AirShare (iOS App)
A native iOS application built in SwiftUI that mimics the Nothing OS dashboard.
*   **Discovery**: Find your Nothing Phone on the local network instantly.
*   **Share Extension**: Send photos and files directly from the iOS Photos/Files app Share Sheet.
*   **Nothing UI**: Custom dot-matrix typography, monochrome widgets, and haptic feedback.

### 2. Unified Clipboard & Drop (macOS)
A background Python daemon that handles the "invisible" heavy lifting.
*   **Universal Clipboard**: Copy text on Mac, paste on Nothing Phone. Copy on Phone, paste on Mac. It just works.
*   **Nothing Drop**: A folder on your Mac (`~/NothingDrop`). Anything you put in it is instantly pushed to your phone's Downloads.
*   **Bypass**: Uses ADB-over-Wi-Fi to circumvent Android's background clipboard restrictions safely.

---

## 🛠 Setup Guide

### The Mac Side (Clipboard & File Sync)
1.  **Install ADB**: Make sure you have `platform-tools` installed (`brew install android-platform-tools`).
2.  **Enable Wireless Debugging**: 
    *   On your Nothing Phone: Developer Options > Wireless Debugging > Enable.
    *   Pair your Mac: `adb pair <IP>:<PORT>`
3.  **Run the Sync**:
    ```bash
    # Clone and setup env
    git clone https://github.com/yourusername/nothing-airshare.git
    cd nothing-airshare
    uv venv && source .venv/bin/activate
    uv pip install pyobjc-framework-Cocoa watchdog Pillow
    
    # Start syncing
    python unified_sync.py
    ```

### The iOS Side (AirShare App)
1.  Open the `NothingApp` folder in Xcode.
2.  Add your "Nothing" font (`NDOT-45.ttf`) to the project.
3.  Build and Run on your iPhone.
4.  **Note**: Make sure to allow "Local Network" permissions when prompted.

---

## 🖤 Aesthetic Credits
This project is a tribute to the design language of [Nothing](https://nothing.tech). All rights to the "Nothing" brand and aesthetic belong to them. We're just fans trying to build a better bridge.

---

## 🤝 Contributing
Have an idea to make the sync faster? Or a way to bring Nothing-style widgets to the iOS lock screen? PRs are more than welcome. Let's build the ecosystem Nothing would be proud of.

*Built with 🖤 for the Nothing Community.*
# Nothing-Air-Share
