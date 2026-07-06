# Changelog

All notable changes to **Nothing AirShare**. The newest build is always on the
[Releases page](https://github.com/Raul909/Nothing-Air-Share/releases/latest).

## v2.9.1 — Background Reliability, Trackpad Overhaul & Universal Media

**Background Connection** *(fixes "wireless debugging keeps stopping" + clipboard dropping out)*
- New persistent **foreground service** holds a high-performance **Wi-Fi lock** + wake lock, so the link survives screen-off and Doze instead of dying in the background
- One-time **battery-optimization exemption** and **notification** prompts on first launch
- **Boot receiver** auto-restarts sync after a reboot — clipboard sync and remote input stay alive

**Trackpad — now behaves like a MacBook**
- **Tap-to-click fixed** — a 0.5 px jitter threshold used to swallow most taps (and every double-tap); replaced with a proper touch-slop
- **Two-finger tap = right-click**, **two-finger drag = scroll**, **double-tap-and-drag** to grab & move
- **Haptic feedback** on clicks and drag start/stop
- **Pointer acceleration** for fast, natural movement; removed a cross-thread race + extra thread hop that were adding input lag

**Media Remote**
- **Volume up / down / mute** buttons added
- **Next / Previous now work** — replaced the Spotify/Music-only AppleScript with system-wide media keys that control whatever is actually playing (Music, Spotify, Safari, Chrome, YouTube, VLC, and more)

**Setup**
- New one-click **`setup_mac.command`** installer + a beginner-friendly setup guide for non-technical users

## v2.8.0 — Connection Stability, Menu Bar Sync & Latency Optimization

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

Older versions (v2.7.x and earlier) are listed on the [Releases page](https://github.com/Raul909/Nothing-Air-Share/releases).
