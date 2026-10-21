# Changelog

All notable changes to **Nothing AirShare**. The newest build is always on the
[Releases page](https://github.com/Raul909/Nothing-Air-Share/releases/latest).

## v2.10.0 — Security, Stability & Performance Overhaul

> **Update both sides:** install the new APK on your phone *and* re-run
> `setup_mac.command` on your Mac. The new APK installs over the old one — no
> uninstall needed, settings are kept.

**Security** *(Mac app — please update)*
- Fixed a critical issue where crafted clipboard text or a file name sent from
  any device on the same Wi-Fi could run commands on the Mac (AppleScript
  injection through notifications and the Accept dialog)
- Incoming file names can no longer write outside the drop folder (`../` paths)
- Logs no longer record clipboard contents, transfer PINs or ADB pairing codes

**Mac — stability**
- All ADB commands have timeouts, so a stuck `adb` can no longer freeze the app
- Works when your phone shows up twice in ADB (USB + Wi-Fi, or mDNS + IP) —
  no more "more than one device/emulator" failures
- A silently dropped wireless-ADB link is detected within 30s instead of the
  menu bar showing **Connected** forever
- Reconnecting no longer overwrites your Mac clipboard with an old phone clip or
  pops a "Do Not Disturb Disabled" notification
- Phone files with spaces in their names now transfer correctly, and files are
  never pulled while the phone is still writing them
- Files received from the phone no longer bounce straight back to it
- Interrupted transfers are cleaned up and reported instead of leaving a
  truncated file that looked successful
- **AirDrop forwarding works again** on current macOS (AirDropped files are
  tagged `sharingd`, which the forwarder didn't recognize)
- **Send Files**, the drop folder and AirDrop forwarding now fall back to Wi-Fi
  when ADB isn't connected (the phone shows an Accept prompt)
- **Find Phone** works over ADB too (the fallback broadcast was being dropped by
  Android)
- Connection status stays accurate when only one of ADB / Wi-Fi drops
- Only one copy of the app can run at a time; logs are written to
  `~/.nothing_sync/airshare.log`

**Mac — performance**
- Notifications no longer block — trackpad input stays smooth while clipboard
  notifications are shown
- The clipboard watcher only touches the main thread when the clipboard
  actually changes; the popover only redraws when something changed
- **Image clipboard sync (Mac → phone over ADB) works** — it used to error on
  every image copy

**Android — stability**
- Fixed crashes when the sync service restarts (e.g. after changing the local
  port), when network discovery fails to start, and when a file arrives after
  the app screen was closed
- Incoming files are declined if nobody can answer the prompt (instead of
  hanging forever), saved only once complete, and show up in Files/Photos
  immediately
- **Send Files** with no device selected now sends to your Mac (it used to do
  nothing); sharing large files no longer freezes the app
- Reconnects to the Mac as soon as Wi-Fi comes back
- The battery level on the Mac no longer goes stale, and is sent on connect
- The **Manual Mac IP** setting now actually works (for networks that block
  discovery)
- The battery-optimization exemption prompt now opens correctly

**Setup**
- `setup_mac.command` keeps your installed app if the build fails, shows where
  the build log is, and quits the old version before installing the new one

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
