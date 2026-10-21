import time
import subprocess
import os
import shutil
import threading
import json
import sqlite3
import base64
import socket
import struct
import hmac
import shlex
import sys
import fcntl
import queue
from AppKit import (
    NSApplication, NSStatusBar, NSMenu, NSMenuItem,
    NSVariableStatusItemLength, NSWorkspace,
    NSPasteboard, NSStringPboardType, NSFilenamesPboardType,
    NSTIFFPboardType, NSImage, NSBitmapImageRep, NSPNGFileType,
    NSSharingService, NSSharingServiceNameSendViaAirDrop,
    NSPopover, NSViewController, NSView, NSTextField, NSColor,
    NSFont, NSButton, NSBezelStyleRounded, NSVisualEffectView,
    NSAppearance, NSProgressIndicator, NSTrackingArea,
    NSRectFill, NSBezierPath, NSAlert, NSPopUpButton,
    NSImageLeft, NSPopoverBehaviorTransient, NSMinYEdge,
    NSMutableAttributedString, NSForegroundColorAttributeName,
    NSFontAttributeName, NSPasteboardTypePNG
)
from Foundation import NSObject, NSURL, NSNetService, NSNetServiceBrowser
import objc
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
import Quartz
from Quartz import CGEventCreateMouseEvent, CGEventPost, kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft, kCGHIDEventTap

last_accessibility_warning_time = 0

# Connection state lock to prevent Bonjour auto-connect and monitor loop from racing (C3)
adb_connect_lock = threading.Lock()
adb_connecting = False

def recv_exact(sock, n):
    """Reliably receive exactly n bytes from a socket, looping until complete.
    Returns the data or raises an exception if the connection closes early."""
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError(f"Connection closed after {len(data)}/{n} bytes")
        data.extend(chunk)
    return bytes(data)

_ax_trusted = None
def _ax_ok():
    global _ax_trusted
    if _ax_trusted: return True
    if AXIsProcessTrusted():
        _ax_trusted = True
        return True
    
    global last_accessibility_warning_time
    now = time.time()
    if now - last_accessibility_warning_time > 60:
        last_accessibility_warning_time = now
        print("[Accessibility] Missing permission")
        send_mac_notification(
            "Accessibility Permission Required",
            "Please enable Python/Terminal in System Settings -> Privacy & Security -> Accessibility."
        )
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    return False

def move_mouse(dx, dy):
    try:
        if not _ax_ok(): return
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        new_x = loc.x + dx * 1.5
        new_y = loc.y + dy * 1.5
        event = CGEventCreateMouseEvent(None, kCGEventMouseMoved, (new_x, new_y), 0)
        CGEventPost(Quartz.kCGHIDEventTap, event)
    except Exception as e:
        print(f"[Mouse Control] Error: {e}")

def click_mouse():
    try:
        if not _ax_ok(): return
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, (loc.x, loc.y), kCGMouseButtonLeft)
        up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, (loc.x, loc.y), kCGMouseButtonLeft)
        CGEventPost(Quartz.kCGHIDEventTap, down)
        CGEventPost(Quartz.kCGHIDEventTap, up)
    except Exception as e:
        print(f"[Mouse Control] Error: {e}")

def set_mouse_button(down):
    try:
        if not _ax_ok(): return
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        ev_type = Quartz.kCGEventLeftMouseDown if down else Quartz.kCGEventLeftMouseUp
        ev = Quartz.CGEventCreateMouseEvent(None, ev_type, loc, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    except Exception as e: pass

def right_click_mouse():
    try:
        if not _ax_ok(): return
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventRightMouseDown, loc, Quartz.kCGMouseButtonRight)
        up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventRightMouseUp, loc, Quartz.kCGMouseButtonRight)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
    except Exception as e: pass

def scroll_wheel(dx, dy):
    try:
        if not _ax_ok(): return
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitPixel, 2, int(dy * 15), int(dx * 15))
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    except Exception as e:
        print(f"[Scroll] Error: {e}")

def _post_aux_key(key_code):
    NX_SYSDEFINED = 8
    event = Quartz.CGEventCreate(None)
    loc = Quartz.CGEventGetLocation(event)
    ev_down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventOtherMouseDown, loc, 0)
    Quartz.CGEventSetType(ev_down, NX_SYSDEFINED)
    Quartz.CGEventSetIntegerValueField(ev_down, Quartz.kCGEventSourceUserData, 0)
    Quartz.CGEventSetIntegerValueField(ev_down, Quartz.kCGKeyboardEventAutorepeat, 0)
    Quartz.CGEventSetIntegerValueField(ev_down, 109, (key_code << 16) | (0xa << 8))
    ev_up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventOtherMouseUp, loc, 0)
    Quartz.CGEventSetType(ev_up, NX_SYSDEFINED)
    Quartz.CGEventSetIntegerValueField(ev_up, Quartz.kCGEventSourceUserData, 0)
    Quartz.CGEventSetIntegerValueField(ev_up, Quartz.kCGKeyboardEventAutorepeat, 0)
    Quartz.CGEventSetIntegerValueField(ev_up, 109, (key_code << 16) | (0xb << 8))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev_up)

def simulate_key_combo(keycode, flags=None):
    if not _ax_ok(): return
    ev_down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
    ev_up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
    if flags:
        flag_mask = 0
        for f in flags:
            flag_mask |= f
        Quartz.CGEventSetFlags(ev_down, flag_mask)
        Quartz.CGEventSetFlags(ev_up, flag_mask)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev_down)
    Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev_up)

def simulate_media_key(key):
    try:
        if not _ax_ok(): return
        if key == "browser_back":
            simulate_key_combo(33, [Quartz.kCGEventFlagMaskCommand])
            return
        elif key == "browser_forward":
            simulate_key_combo(30, [Quartz.kCGEventFlagMaskCommand])
            return
        elif key == "mission_control":
            simulate_key_combo(126, [Quartz.kCGEventFlagMaskControl])
            return
        elif key == "app_expose":
            simulate_key_combo(125, [Quartz.kCGEventFlagMaskControl])
            return
        elif key == "space_left":
            simulate_key_combo(123, [Quartz.kCGEventFlagMaskControl])
            return
        elif key == "space_right":
            simulate_key_combo(124, [Quartz.kCGEventFlagMaskControl])
            return

        keys = {
            "play_pause": 16,
            "next": 17,
            "prev": 18,
            "vol_up": 0,
            "vol_down": 1,
            "mute": 7
        }
        code = keys.get(key)
        if code is not None:
            _post_aux_key(code)
    except Exception as e:
        print(f"[Media] Error: {e}")

# Ensure Homebrew and common directories are in PATH for subprocess calls
for p in ["/opt/homebrew/bin", "/usr/local/bin"]:
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{p}:{os.environ.get('PATH', '')}"

# Configuration
APP_VERSION = "2.9.1"
DROP_ZONE_MAC = os.path.expanduser("~/NothingDrop")
DROP_ZONE_ANDROID = "/sdcard/Download/NothingDrop"
TEMP_DIR = os.path.expanduser("~/.nothing_sync_temp")
CONFIG_DIR = os.path.expanduser("~/.nothing_sync")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DB_FILE = os.path.join(CONFIG_DIR, "history.db")
LOG_FILE = os.path.join(CONFIG_DIR, "airshare.log")
LOG_MAX_BYTES = 2 * 1024 * 1024

# ── Network constants (single source of truth) ──────────────────────────────
# LAN duplex session port: the Mac TCP server listens here and the phone opens a
# persistent connection to it. All clip/dnd/battery/command/file messages flow
# over this one socket. See PeerSession below.
LAN_PORT = 53317
# ADB reverse-forward endpoints used only for the optional ADB fallback command
# path: `adb reverse tcp:ADB_REVERSE_PORT tcp:LAN_PORT` maps a phone-local port
# to the Mac server so the phone can reach the Mac over 127.0.0.1 via USB/ADB.
ADB_REVERSE_PORT = 53319
# Protocol
PROTO_VERSION = 1
HEARTBEAT_INTERVAL = 15.0   # seconds between pings on an idle session
HEARTBEAT_TIMEOUT = 35.0    # drop a session with no traffic for this long
# ADB fallback reconnect: give up on the cached address after this many tries
# (the wireless-debugging port rotates, so a stale address never recovers). Once
# exhausted we wait for Bonjour to re-discover the phone and trigger a fresh connect.
MAX_ADB_RECONNECT_ATTEMPTS = 5

# Ensure directories exist
os.makedirs(DROP_ZONE_MAC, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

def remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass

# Clipboard images left behind by earlier versions (one PNG per copy, never deleted)
for _name in os.listdir(TEMP_DIR):
    if _name.startswith("clip_img_"):
        remove_quietly(os.path.join(TEMP_DIR, _name))

# Global sync state
CURRENT_CLIPBOARD_CONTENT = ""
sync_state_lock = threading.Lock()
LAST_CHANGE_COUNT = -1
app_delegate = None
db = None
bonjour_manager = None

# Live duplex sessions to connected phones, keyed by peer name. Populated when a
# phone sends a `hello` over the LAN socket (see handle_mac_incoming_connection).
peer_sessions = {}
peer_sessions_lock = threading.Lock()

# Helper app configuration for Option B clipboard sync
HELPER_PACKAGE = "com.nothing.airshare"
HELPER_RECEIVER = "com.nothing.airshare/.ClipboardReceiver"
AIRSHARE_RECEIVER = "com.nothing.airshare/.ClipboardReceiver"

# Connection state is the union of two independent links: the ADB stream and the
# LAN session(s). Each source flips its own flag and calls refresh_connection_state.
adb_link_up = False

# Serial of the device all device-scoped adb commands are pinned to. Without it a
# phone listed twice (USB + Wi-Fi, or mDNS name + IP:port) makes every
# `adb shell` fail with "more than one device/emulator".
ADB_SERIAL = None


def adb(*args, timeout=15, text=True, device=True):
    """Run an adb command with a timeout so a wedged adb server can't hang a
    worker thread forever. Never raises; a timeout returns returncode 124."""
    cmd = ["adb"]
    if device and ADB_SERIAL:
        cmd += ["-s", ADB_SERIAL]
    cmd += [str(a) for a in args]
    empty = "" if text else b""
    try:
        return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[ADB] Timed out after {timeout}s: adb {' '.join(cmd[1:4])}")
        return subprocess.CompletedProcess(cmd, 124, empty, "timeout" if text else b"timeout")
    except OSError as e:
        print(f"[ADB] Failed to run adb: {e}")
        return subprocess.CompletedProcess(cmd, 127, empty, str(e) if text else str(e).encode())


def list_adb_devices():
    """Serials of devices in the ready ('device') state."""
    res = adb("devices", device=False, timeout=10)
    serials = []
    for line in res.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def pick_adb_device(serials):
    """Prefer the current serial, then the last address we connected to, then a
    plain IP:port entry (stable for the session) over an mDNS service name."""
    if ADB_SERIAL in serials:
        return ADB_SERIAL
    last = load_config().get("last_address")
    if last in serials:
        return last
    for s in serials:
        if ":" in s and not s.startswith("adb-"):
            return s
    return serials[0] if serials else None


def refresh_connection_state():
    if app_delegate:
        app_delegate.set_connected(adb_link_up or has_live_session())

# Config helpers
def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f)
    except Exception as e:
        print(f"[Config] Error saving config: {e}")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config] Error loading config: {e}")
    return {}

# Track last pulled file for AirDrop forwarding
LAST_PULLED_FILE = None

def resolve_mdns_hostname(hostname):
    try:
        if hostname.endswith('.'):
            hostname = hostname[:-1]
        return socket.gethostbyname(hostname)
    except Exception as e:
        print(f"[Bonjour] Failed to resolve hostname '{hostname}' via socket: {e}")
        return hostname

# Bonjour Manager and P2P File Sharing Support
class BonjourManager(NSObject):
    def init(self):
        self = objc.super(BonjourManager, self).init()
        if self:
            self.discovered_devices = {}  # name -> (host, port)
            self.browser = None
            self.adb_browser = None
            self.service = None
            self.services_resolving = []
        return self

    def start(self):
        # 1. Advertise macOS Share service
        self.service = NSNetService.alloc().initWithDomain_type_name_port_(
            "local.",
            "_nothing-share._tcp.",
            "Mac Nothing Share",
            53317
        )
        self.service.setDelegate_(self)
        self.service.publish()

        # 2. Browse for other devices
        self.browser = NSNetServiceBrowser.alloc().init()
        self.browser.setDelegate_(self)
        self.browser.searchForServicesOfType_inDomain_("_nothing-share._tcp.", "local.")

        # 3. Browse for Android Wireless Debugging
        self.adb_browser = NSNetServiceBrowser.alloc().init()
        self.adb_browser.setDelegate_(self)
        self.adb_browser.searchForServicesOfType_inDomain_("_adb-tls-connect._tcp.", "local.")
        print("[Bonjour] Started advertising, browsing for nothing-share and adb-tls-connect...")

    # NSNetServiceBrowser delegate methods
    def netServiceBrowser_didFindService_moreComing_(self, browser, service, more):
        print(f"[Bonjour] Found service: {service.name()} ({service.type()})")
        service.setDelegate_(self)
        if not hasattr(self, "services_resolving") or self.services_resolving is None:
            self.services_resolving = []
        self.services_resolving.append(service)
        service.resolveWithTimeout_(5.0)

    def netServiceBrowser_didRemoveService_moreComing_(self, browser, service, more):
        name = service.name()
        print(f"[Bonjour] Removed service: {name}")
        if name in self.discovered_devices:
            del self.discovered_devices[name]
            if app_delegate:
                app_delegate.update_menu()

    # NSNetService delegate methods
    def netServiceDidResolveAddress_(self, service):
        host = service.hostName()
        port = service.port()
        stype = service.type()
        print(f"[Bonjour] Resolved {service.name()} ({stype}) to {host}:{port}")
        
        if hasattr(self, "services_resolving") and service in self.services_resolving:
            try:
                self.services_resolving.remove(service)
            except:
                pass

        if "_adb-tls-connect" in stype:
            ip = resolve_mdns_hostname(host)
            addr = f"{ip}:{port}"
            print(f"[Bonjour ADB] Discovered Wireless Debugging at {addr}. Dynamic connect...")
            threading.Thread(target=run_adb_connect_safe, args=(addr,), daemon=True).start()
        elif self.service is not None and service.name() == self.service.name():
            return  # our own advertisement — don't list the Mac as a nearby phone
        else:
            self.discovered_devices[service.name()] = (host, port)
            if app_delegate:
                app_delegate.update_menu()

    def netService_didNotPublish_(self, service, errorDict):
        print(f"[Bonjour Error] Publishing failed: {errorDict}")

    def netService_didNotResolve_(self, service, errorDict):
        print(f"[Bonjour Error] Resolution failed for {service.name()}: {errorDict}")
        if hasattr(self, "services_resolving") and service in self.services_resolving:
            try:
                self.services_resolving.remove(service)
            except:
                pass


# ── Duplex LAN session ──────────────────────────────────────────────────────
class PeerSession:
    """Wraps one persistent phone<->Mac socket so the daemon can *push* messages
    (clipboard, DND) back to the phone over the same connection the phone opened.

    Writes are serialized with a lock; reads happen on the connection's own
    handler thread (handle_mac_incoming_connection)."""

    def __init__(self, conn, name):
        self.conn = conn
        self.name = name
        self.write_lock = threading.Lock()
        self.last_rx = time.time()
        self.alive = True

    def send(self, msg_dict):
        """Send a framed JSON message (4-byte BE length prefix + UTF-8 JSON)."""
        if not self.alive:
            return False
        try:
            payload = json.dumps(msg_dict).encode('utf-8')
            frame = struct.pack('!I', len(payload)) + payload  # one write per frame
            with self.write_lock:
                self.conn.sendall(frame)
            return True
        except Exception as e:
            print(f"[Session] Send to {self.name} failed: {e}")
            self.close()
            return False

    def close(self):
        self.alive = False
        # Shut the socket down so the reader thread blocked in recv() wakes up
        # immediately instead of waiting out its 45s timeout.
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        unregister_session(self)


def register_session(session):
    with peer_sessions_lock:
        previous = peer_sessions.get(session.name)
        peer_sessions[session.name] = session
    # The phone reconnected (Wi-Fi roam, app restart) before its old socket timed
    # out — retire the stale one now rather than leaking it for a minute.
    if previous is not None and previous is not session:
        previous.close()
    print(f"[Session] Registered live session with {session.name}")
    refresh_connection_state()


def unregister_session(session):
    removed = False
    with peer_sessions_lock:
        if peer_sessions.get(session.name) is session:
            del peer_sessions[session.name]
            removed = True
    if removed:
        print(f"[Session] Closed session with {session.name}")
        refresh_connection_state()


def has_live_session():
    with peer_sessions_lock:
        return bool(peer_sessions)


def push_to_phones(msg_dict):
    """Push a message to every live phone session. Returns True if at least one
    session received it."""
    with peer_sessions_lock:
        sessions = list(peer_sessions.values())
    delivered = False
    for s in sessions:
        if s.send(msg_dict):
            delivered = True
    return delivered


def heartbeat_loop():
    """Ping idle sessions and reap dead ones so a silently-dropped socket is
    detected within ~HEARTBEAT_TIMEOUT instead of on next user action."""
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        with peer_sessions_lock:
            sessions = list(peer_sessions.values())
        now = time.time()
        for s in sessions:
            if now - s.last_rx > HEARTBEAT_TIMEOUT:
                print(f"[Session] {s.name} timed out (no traffic)")
                s.close()
            else:
                s.send({"type": "ping"})


def mac_tcp_server_loop():
    # Keep retrying the bind: right after a relaunch the previous instance may
    # still hold the port for a few seconds, and giving up here used to leave the
    # app running with no LAN server at all.
    backoff = 1
    while True:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(('0.0.0.0', LAN_PORT))
            server.listen(16)
            break
        except OSError as e:
            server.close()
            print(f"[TCP Server] Bind failed ({e}); retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
    print(f"[TCP Server] Listening for peer transfers and commands on port {LAN_PORT}")

    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_mac_incoming_connection, args=(conn,), daemon=True).start()
        except Exception:
            time.sleep(1)


def handle_mac_incoming_connection(conn):
    # A connection becomes a persistent duplex `session` once the phone sends a
    # `hello`. Until then (and for one-shot file transfers) it behaves exactly as
    # before, so older phones that never send `hello` keep working over ADB.
    session = None
    try:
        print(f"[TCP Server] Connection accepted: {conn.getpeername()}")
        conn.settimeout(30.0)
        # Set TCP_NODELAY to disable Nagle's algorithm — critical for low-latency
        # mouse move and media commands (L6)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        while True:
            # Check for binary mouse_move protocol first (1-byte type marker)
            # Binary protocol: 0x01 (1 byte) + dx (4 bytes float32 BE) + dy (4 bytes float32 BE) = 9 bytes
            first_byte = conn.recv(1)
            if not first_byte:
                break

            if session:
                session.last_rx = time.time()

            if first_byte == b'\x01':
                # Binary mouse_move protocol (L3)
                move_data = recv_exact(conn, 8)  # 2x float32
                dx, dy = struct.unpack('!ff', move_data)
                move_mouse(dx, dy)
                continue
            elif first_byte == b'\x02':
                # Binary scroll protocol
                scroll_data = recv_exact(conn, 8)
                dx, dy = struct.unpack('!ff', scroll_data)
                scroll_wheel(dx, dy)
                continue

            # Standard JSON protocol: first byte is part of 4-byte length prefix
            remaining_len_bytes = recv_exact(conn, 3)
            len_bytes = first_byte + remaining_len_bytes
            meta_len = struct.unpack('!I', len_bytes)[0]
            if meta_len > 100000:
                break

            # Use recv_exact for reliable reads (C1)
            payload_bytes = recv_exact(conn, meta_len)

            payload_str = payload_bytes.decode('utf-8')
            data = json.loads(payload_str)

            msg_type = data.get("type", "file")
            if msg_type not in ("mouse_move", "ping", "pong"):
                print(f"[TCP Server] Received command: {msg_type}")

            if msg_type == "hello":
                # Promote this connection to a persistent duplex session so the
                # daemon can push clipboard/DND back over the same socket.
                name = data.get("name", "Nothing Phone")
                conn.settimeout(HEARTBEAT_TIMEOUT + 10)
                session = PeerSession(conn, name)
                register_session(session)
                if app_delegate:
                    app_delegate.device_model = name
                session.send({"type": "hello", "name": "MacBook", "protoVersion": PROTO_VERSION})
            elif msg_type == "clip":
                apply_incoming_clip(data)
            elif msg_type == "dnd":
                is_dnd = bool(data.get("on", False))
                status_text = "Enabled" if is_dnd else "Disabled"
                print(f"[Phone] DND {status_text}")
                send_mac_notification("Nothing Phone", f"Do Not Disturb {status_text}")
            elif msg_type == "ping":
                if session:
                    session.send({"type": "pong"})
            elif msg_type == "pong":
                pass  # liveness already refreshed via last_rx above
            elif msg_type == "file":
                # Set dynamic timeout based on filesize (C5)
                filesize = data.get("fileSize", 0)
                dynamic_timeout = max(30.0, filesize / (1024 * 1024) * 5)  # 5s per MB, min 30s
                conn.settimeout(dynamic_timeout)
                handle_incoming_file_data(conn, data)
                if session:
                    conn.settimeout(HEARTBEAT_TIMEOUT + 10)  # restore session timeout
                else:
                    break  # standalone file transfer is one-shot
            elif msg_type == "mouse_move":
                # JSON fallback for backward compatibility
                dx = data.get("dx", 0.0)
                dy = data.get("dy", 0.0)
                move_mouse(dx, dy)
            elif msg_type == "mouse_click":
                click_mouse()
            elif msg_type == "mouse_down":
                set_mouse_button(True)
            elif msg_type == "mouse_up":
                set_mouse_button(False)
            elif msg_type == "mouse_right_click":
                right_click_mouse()
            elif msg_type == "scroll":
                dx = data.get("dx", 0.0)
                dy = data.get("dy", 0.0)
                scroll_wheel(dx, dy)
            elif msg_type == "media_key":
                key = data.get("key")
                simulate_media_key(key)
            elif msg_type == "battery":
                level = data.get("level", 50)
                charging = data.get("charging", False)
                if app_delegate:
                    app_delegate.update_battery_level_charging(level, charging)
    except ConnectionError as e:
        print(f"[TCP Server] Connection closed: {e}")
    except Exception as e:
        print(f"[TCP Server] Error: {e}")
    finally:
        if session:
            session.close()
        try:
            conn.close()
        except Exception:
            pass


def safe_filename(name, default="file.bin"):
    """Reduce a peer-supplied file name to a plain basename so it can't escape the
    destination folder ('../../.zshrc') or hide itself with a leading dot."""
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = "".join(c for c in name if c >= " " and c != "\x7f").strip().lstrip(".")
    if not name:
        return default
    base, ext = os.path.splitext(name)
    return base[:200] + ext[:20]


def unique_path(dest_dir, filename):
    """Return dest_dir/filename, adding _1, _2... until it doesn't collide."""
    dest_path = os.path.join(dest_dir, filename)
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(dest_path):
        dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
        counter += 1
    return dest_path


ACCEPT_PROMPT_SCRIPT = '''on run argv
tell application "System Events"
    activate
    set r to display dialog (item 1 of argv) with title "Nothing AirShare" buttons {"Decline", "Accept"} default button "Accept" giving up after 100
end tell
if gave up of r then return "Decline"
return button returned of r
end run'''


def handle_incoming_file_data(conn, metadata):
    try:
        sender = str(metadata.get("senderName", "Unknown Device"))[:64]
        filename = safe_filename(metadata.get("fileName"))
        filesize = int(metadata.get("fileSize", 0) or 0)
        provided_pin = str(metadata.get("pin", ""))

        config = load_config()
        expected_pin = str(config.get("security_pin", "1234"))
        if filesize < 0 or not hmac.compare_digest(provided_pin, expected_pin):
            print("[P2P Receiver] Unauthorized transfer attempt (Invalid PIN)")
            conn.sendall(bytes([0x02]))
            return

        print(f"[P2P Receiver] Incoming file request from {sender}: {filename} ({filesize} bytes)")

        # 3. Prompt user via AppleScript (text goes in as argv, see NOTIFY_SCRIPT)
        size_mb = filesize / 1024.0 / 1024.0
        prompt = (f"Incoming file share from {sender}\n\nFile: {filename}\n"
                  f"Size: {size_mb:.2f} MB\n\nDo you want to accept this file?")
        try:
            proc = subprocess.run(["osascript", "-e", ACCEPT_PROMPT_SCRIPT, prompt],
                                  capture_output=True, text=True, timeout=120)
            accepted = proc.stdout.strip() == "Accept"
        except subprocess.TimeoutExpired:
            accepted = False

        # 4. Respond with approval code
        if accepted:
            conn.sendall(bytes([0x01]))  # Accept
            print("[P2P Receiver] User accepted the transfer. Receiving stream...")
            send_mac_notification("Nothing AirShare", f"Receiving '{filename}' from {sender}...")

            # 5. Receive into a hidden .part file and only reveal it once complete,
            # so an interrupted transfer never leaves a truncated file behind.
            dest_path = unique_path(DROP_ZONE_MAC, filename)
            part_path = os.path.join(DROP_ZONE_MAC, f".{os.path.basename(dest_path)}.part")
            received = 0
            try:
                with open(part_path, 'wb') as f:
                    while received < filesize:
                        to_read = min(262144, filesize - received)  # 256KB buffer (L5)
                        chunk = conn.recv(to_read)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                if received != filesize:
                    raise ConnectionError(f"stream ended after {received}/{filesize} bytes")
                ignore_drop_path(dest_path)
                os.replace(part_path, dest_path)
            except Exception:
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                raise

            print(f"[P2P Receiver] Successfully received: {dest_path}")

            # Import to macOS Spotlight index and notify
            subprocess.run(["mdimport", dest_path], capture_output=True, timeout=30)
            send_mac_notification("Nothing AirShare Success", f"Received '{os.path.basename(dest_path)}' from {sender}")
        else:
            conn.sendall(bytes([0x02]))  # Decline
            print("[P2P Receiver] User declined the transfer.")
    except Exception as e:
        print(f"[P2P Receiver Error] Connection failed: {e}")
        send_mac_notification("Nothing AirShare Error", "File transfer from phone failed.")


def mac_send_file_to_peer(file_path, device_name, host, port):
    sock = None
    try:
        send_mac_notification("Nothing AirShare", f"Connecting to {device_name}...")
        sock = socket.create_connection((host, port), timeout=10.0)
        # The phone shows an Accept/Decline dialog; give the user time to answer.
        sock.settimeout(130.0)

        config = load_config()
        # 1. Send metadata JSON
        filename = os.path.basename(file_path)
        filesize = os.path.getsize(file_path)
        metadata = {
            "senderName": "MacBook",
            "fileName": filename,
            "fileSize": filesize,
            "pin": config.get("security_pin", "1234")
        }
        meta_str = json.dumps(metadata)
        meta_bytes = meta_str.encode('utf-8')

        sock.sendall(struct.pack('!I', len(meta_bytes)))
        sock.sendall(meta_bytes)

        send_mac_notification("Nothing AirShare", f"Waiting for {device_name} to accept...")

        # 2. Wait for response byte
        res = sock.recv(1)
        if res and res[0] == 0x01:
            send_mac_notification("Nothing AirShare", f"Sending '{filename}' to {device_name}...")
            sock.settimeout(30.0)

            # 3. Stream data (zero-copy from the page cache where supported)
            with open(file_path, 'rb') as f:
                sock.sendfile(f)

            print(f"[P2P Sender] Sent {filename} to {device_name}")
            send_mac_notification("Nothing AirShare Success", f"Sent '{filename}' to {device_name} successfully!")
        else:
            send_mac_notification("Nothing AirShare", f"{device_name} declined the transfer request.")

    except Exception as e:
        print(f"[P2P Sender Error] Transfer failed: {e}")
        send_mac_notification("Nothing AirShare Error", f"Failed to send: {e}")
    finally:
        if sock:
            sock.close()

# Watcher for iOS AirDropped files in ~/Downloads
class DownloadsAirDropHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            filepath = event.src_path
            filename = os.path.basename(filepath)
            if filename.startswith('.'):
                return
            threading.Thread(target=self.process_maybe_airdrop, args=(filepath,), daemon=True).start()

    def process_maybe_airdrop(self, filepath):
        filename = os.path.basename(filepath)
        # Give macOS a short moment to write extended attributes
        time.sleep(0.5)
        
        if not self.is_airdrop_file(filepath):
            return
        if not (adb_link_up or find_phone_peer()):
            print(f"[AirDrop Forwarder] Phone not reachable; leaving {filename} on the Mac")
            return

        print(f"[AirDrop Forwarder] Detected iOS AirDropped file: {filename}")
        send_mac_notification("AirDrop Forwarder", f"Forwarding iOS AirDrop to Nothing Phone: {filename}")
        
        if wait_until_file_settles(filepath):
            send_file_to_phone(filepath, notify_title="Received from iOS")

    def is_airdrop_file(self, filepath):
        try:
            if not os.path.exists(filepath):
                return False
            # The quarantine agent for AirDropped files is "sharingd" on current
            # macOS (older releases wrote "AirDrop").
            res = subprocess.run(["xattr", "-p", "com.apple.quarantine", filepath], capture_output=True, text=True, timeout=2)
            agent = res.stdout.split(";")[2] if res.returncode == 0 and res.stdout.count(";") >= 2 else ""
            return agent in ("sharingd", "AirDrop")
        except Exception:
            pass
        return False


# SQLite Clipboard History helper
class ClipboardHistoryDB:
    """One shared connection (was: a new one per call) plus an in-memory copy of
    the newest rows, so the popover's 2s refresh never touches the disk."""
    CACHE_SIZE = 10
    KEEP = 50

    def __init__(self):
        self.db_path = DB_FILE
        self.lock = threading.Lock()
        self.conn = None
        self.recent = []
        self.init_db()

    def init_db(self):
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            self.conn.commit()
            rows = self.conn.execute("SELECT content FROM history ORDER BY id DESC LIMIT ?", (self.CACHE_SIZE,))
            self.recent = [row[0] for row in rows]
        except Exception as e:
            print(f"[DB Error] Init failed: {e}")

    def add_item(self, content):
        if not content or len(content.strip()) == 0:
            return
        if len(content) > 10000:  # Skip storing extremely long text/data
            return
        with self.lock:
            if self.recent and self.recent[0] == content:
                return
            self.recent = [content] + self.recent[:self.CACHE_SIZE - 1]
            try:
                with self.conn:  # one transaction
                    self.conn.execute("INSERT INTO history (content, timestamp) VALUES (?, ?)", (content, time.time()))
                    self.conn.execute("DELETE FROM history WHERE id NOT IN "
                                      "(SELECT id FROM history ORDER BY id DESC LIMIT ?)", (self.KEEP,))
            except Exception as e:
                print(f"[DB Error] Insert failed: {e}")

    def get_history(self):
        with self.lock:
            return list(self.recent)

# Notification Helpers
# Untrusted text (clipboard contents, peer-supplied file names) is passed to
# osascript as argv, never spliced into the script source — quote-escaping alone
# can be bypassed with a backslash and turned into `do shell script`.
NOTIFY_SCRIPT = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run'

# Launching osascript takes 100-300ms. Notifications are queued to one worker
# instead of blocking the caller — which was often the LAN session reader, so
# every clipboard notification also stalled trackpad input behind it.
_notify_queue = queue.Queue(maxsize=32)

def _post_notification(title, message):
    try:
        subprocess.run(["osascript", "-e", NOTIFY_SCRIPT, title, message],
                       capture_output=True, timeout=10)
    except Exception as e:
        print(f"[Notification] Failed to send macOS notification: {e}")

def _notification_worker():
    while True:
        _post_notification(*_notify_queue.get())

threading.Thread(target=_notification_worker, daemon=True, name="notifications").start()

def send_mac_notification(title, message, wait=False):
    if wait:
        _post_notification(str(title), str(message))
        return
    try:
        _notify_queue.put_nowait((str(title), str(message)))
    except queue.Full:
        pass  # a burst is already queued; dropping one beats blocking the caller

def send_android_notification(title, message):
    try:
        adb("shell", f"cmd notification post -S bigtext -t {shlex.quote(title)} "
                     f"nothing_sync {shlex.quote(message)}", timeout=10)
    except Exception as e:
        print(f"[Notification] Failed to send Android notification: {e}")

# Files we wrote into a watched folder ourselves (received from the phone). The
# drop-folder watcher skips these so they don't bounce straight back to the phone.
_ignored_drop_paths = {}
_ignored_drop_lock = threading.Lock()

def ignore_drop_path(path, ttl=60):
    now = time.time()
    with _ignored_drop_lock:
        for p, expiry in list(_ignored_drop_paths.items()):
            if expiry < now:
                del _ignored_drop_paths[p]
        _ignored_drop_paths[os.path.realpath(path)] = now + ttl

def is_ignored_drop_path(path):
    with _ignored_drop_lock:
        expiry = _ignored_drop_paths.get(os.path.realpath(path))
    return expiry is not None and expiry > time.time()

# Smart File Routing and Spotlight Import
def pull_file_from_android(remote_name):
    remote_path = f"/sdcard/Android/data/com.nothing.airshare/files/ToMac/{remote_name}"
    filename = safe_filename(remote_name)
    temp_local_path = os.path.join(TEMP_DIR, filename)

    try:
        # Pull file to temp folder first to avoid half-written files
        res = adb("pull", remote_path, temp_local_path, timeout=600)
        if res.returncode != 0:
            print(f"[Drop] Failed to pull {filename}: {res.stderr.strip()}")
            return

        # Delete from Android (quoted: the name was chosen on the phone)
        adb("shell", f"rm -f {shlex.quote(remote_path)}")
        
        # Smart routing based on file extension
        ext = os.path.splitext(filename)[1].lower()
        
        pictures_dir = os.path.expanduser("~/Pictures/NothingDrop")
        documents_dir = os.path.expanduser("~/Documents/NothingDrop")
        downloads_dir = os.path.expanduser("~/NothingDrop") # fallback
        
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic']:
            dest_dir = pictures_dir
        elif ext in ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.csv']:
            dest_dir = documents_dir
        else:
            dest_dir = downloads_dir
            
        os.makedirs(dest_dir, exist_ok=True)
        # Prevent file overwrite by appending suffix
        final_path = unique_path(dest_dir, filename)
        ignore_drop_path(final_path)
        shutil.move(temp_local_path, final_path)
        print(f"[Drop] Pulled and routed {filename} to {final_path}")
        
        # Import to macOS Spotlight index
        subprocess.run(["mdimport", final_path], capture_output=True, timeout=30)

        # Track last pulled file for AirDrop
        global LAST_PULLED_FILE
        LAST_PULLED_FILE = final_path
        if app_delegate:
            app_delegate.update_menu()
        
        # macOS Notification
        send_mac_notification("Nothing Drop", f"Received {filename} (Saved in {os.path.basename(dest_dir)})")
        
    except Exception as e:
        print(f"[Drop] Error during file pull: {e}")
        if os.path.exists(temp_local_path):
            try:
                os.remove(temp_local_path)
            except:
                pass

def wait_until_file_settles(path, interval=0.5, timeout=900):
    """Block until a file stops growing (still being copied or AirDropped).
    Returns False if it disappears or never settles."""
    deadline = time.time() + timeout
    try:
        last = os.path.getsize(path)
        while time.time() < deadline:
            time.sleep(interval)
            size = os.path.getsize(path)
            if size == last:
                return True
            last = size
    except OSError:
        return False
    return False


def push_file_over_adb(local_path):
    filename = os.path.basename(local_path)
    adb("shell", f"mkdir -p {DROP_ZONE_ANDROID}")
    res = adb("push", local_path, f"{DROP_ZONE_ANDROID}/{filename}", timeout=900)
    if res.returncode != 0:
        print(f"[Sync] ADB push of {filename} failed: {res.stderr.strip()}")
        return False
    return True


def find_phone_peer():
    """A phone advertising _nothing-share._tcp over Bonjour, for LAN transfers."""
    if not bonjour_manager:
        return None
    for name, (host, port) in dict(bonjour_manager.discovered_devices).items():
        return name, host, port
    return None


def send_file_to_phone(local_path, notify_title="Received", confirm_on_mac=False):
    """Deliver a Mac file to the phone over whichever link is up: a silent ADB
    push into Download/NothingDrop, or a LAN transfer the phone has to accept.
    Previously only ADB was tried, so LAN-only setups couldn't send at all."""
    filename = os.path.basename(local_path)
    if adb_link_up and push_file_over_adb(local_path):
        print(f"[Sync] Pushed to Phone over ADB: {filename}")
        send_android_notification("Nothing Drop", f"{notify_title}: {filename}")
        if confirm_on_mac:
            send_mac_notification("Nothing AirShare", f"Successfully sent {filename} to phone.")
        return True
    peer = find_phone_peer()
    if peer:
        name, host, port = peer
        mac_send_file_to_peer(local_path, name, host, port)
        return True
    print(f"[Sync] No phone link available for {filename}")
    send_mac_notification("Nothing AirShare", f"Couldn't send {filename}: phone not connected.")
    return False


# File Drop Handler (Mac -> Android)
class MacDropHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            filename = os.path.basename(event.src_path)
            if filename.startswith('.') or is_ignored_drop_path(event.src_path):
                return
            print(f"[Drop] New local file detected: {filename}")
            threading.Thread(target=self.push_to_android, args=(event.src_path,), daemon=True).start()

    def push_to_android(self, local_path):
        # Let file writing finish on Mac
        if wait_until_file_settles(local_path):
            send_file_to_phone(local_path)

# Mac Pasteboard Interfacing
class ClipboardHelper(NSObject):
    def readClipboard_(self, context):
        pb = NSPasteboard.generalPasteboard()
        change_count = pb.changeCount()
        
        global LAST_CHANGE_COUNT
        if change_count == LAST_CHANGE_COUNT:
            context['result'] = (None, change_count)
            return
        
        LAST_CHANGE_COUNT = change_count
        context['result'] = (None, change_count)

        # 1. Check for Files
        if pb.availableTypeFromArray_([NSFilenamesPboardType]):
            files = pb.propertyListForType_(NSFilenamesPboardType)
            if files:
                context['result'] = ({"type": "file", "data": files[0]}, change_count)
                return

        # 2. Check for Images. Only the ADB path can deliver them, so skip the
        # (main-thread) PNG encode entirely when it's down and fall back to text.
        if adb_link_up and pb.availableTypeFromArray_([NSTIFFPboardType, NSPasteboardTypePNG]):
            try:
                # NSPasteboardTypePNG is the pasteboard type; NSPNGFileType is a
                # bitmap format enum and made dataForType_ raise on every copy.
                image_data = pb.dataForType_(NSPasteboardTypePNG)
                if not image_data:
                    image = NSImage.alloc().initWithPasteboard_(pb)
                    if image:
                        tiff_data = image.TIFFRepresentation()
                        bitmap = NSBitmapImageRep.imageRepWithData_(tiff_data)
                        image_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
            except Exception as e:
                print(f"[Clipboard] Could not read image: {e}")
                image_data = None

            if image_data:
                temp_path = os.path.join(TEMP_DIR, f"clip_img_{change_count}.png")
                image_data.writeToFile_atomically_(temp_path, True)
                context['result'] = ({"type": "image", "data": temp_path}, change_count)
                return

        # 3. Check for Text
        content = pb.stringForType_(NSStringPboardType)
        if content:
            context['result'] = ({"type": "text", "data": content}, change_count)
            return
            
        context['result'] = (None, change_count)

    def writeClipboard_(self, context):
        type_ = context.get('type')
        data = context.get('data')
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        if type_ == "text":
            pb.setString_forType_(data, NSStringPboardType)
        elif type_ == "image":
            image = NSImage.alloc().initByReferencingFile_(data)
            if image:
                pb.writeObjects_([image])

clip_helper = ClipboardHelper.alloc().init()

def get_mac_clipboard():
    ctx = {}
    clip_helper.performSelectorOnMainThread_withObject_waitUntilDone_(
        "readClipboard:", ctx, True
    )
    return ctx.get('result', (None, LAST_CHANGE_COUNT))

def set_mac_clipboard(type, data):
    ctx = {'type': type, 'data': data}
    clip_helper.performSelectorOnMainThread_withObject_waitUntilDone_(
        "writeClipboard:", ctx, True
    )

def apply_incoming_clip(data):
    """Apply a `clip` message pushed from the phone to the Mac pasteboard, with
    echo-suppression via CURRENT_CLIPBOARD_CONTENT so the value can't ping-pong."""
    global CURRENT_CLIPBOARD_CONTENT
    if data.get("format", "text") != "text":
        return  # image clips arrive over the file channel
    text = data.get("data", "")
    if not text:
        return
    with sync_state_lock:
        if text == CURRENT_CLIPBOARD_CONTENT:
            return
        CURRENT_CLIPBOARD_CONTENT = text
        set_mac_clipboard("text", text)
    # Disk and notification work happens outside the lock so the clipboard
    # watcher and the other transport aren't held up behind it.
    print(f"[Phone] Clipboard changed ({len(text)} chars)")
    if db:
        db.add_item(text)
    send_mac_notification("Nothing Clipboard", f"Copied: {text[:30]}")

def detect_helper_package():
    global HELPER_PACKAGE, HELPER_RECEIVER
    try:
        res = adb("shell", "pm list packages", timeout=10)
        if res.returncode == 0:
            if "com.nothing.airshare" in res.stdout:
                HELPER_PACKAGE = "com.nothing.airshare"
                HELPER_RECEIVER = "com.nothing.airshare/.ClipboardReceiver"
                print("[ADB] Custom Nothing AirShare Android app detected for clipboard sync!")
            elif "com.potatodigua.clipboardhelper" in res.stdout:
                HELPER_PACKAGE = "com.potatodigua.clipboardhelper"
                HELPER_RECEIVER = "com.potatodigua.clipboardhelper/.ClipperReceiver"
                print("[ADB] Third-party ClipboardHelper detected for clipboard sync!")
            else:
                HELPER_PACKAGE = "com.nothing.airshare"
                HELPER_RECEIVER = "com.nothing.airshare/.ClipboardReceiver"
                print("[ADB Warning] No clipboard helper app detected on phone. Sync will be disabled.")
    except Exception as e:
        print(f"[ADB Warning] Failed to detect helper app: {e}")

# Push to Android Clipboard
def push_to_android_clipboard(item):
    try:
        if item["type"] == "text":
            quoted_text = shlex.quote(item["data"])
            
            # 1. Update system clipboard directly using privileged adb shell cmd clipboard (always works)
            adb("shell", f"cmd clipboard set-text {quoted_text}")
            
            # 2. Also send broadcast to helper app so it can show Toast and update UI
            res = adb("shell", f"am broadcast -n {shlex.quote(HELPER_RECEIVER)} -a clipper.set -f 32 -e text {quoted_text}")
            if res.returncode == 0:
                print(f"[Sync] Text pushed to Phone ({len(item['data'])} chars)")
            else:
                print(f"[Sync Warning] Failed to push clipboard: {res.stderr.strip() or res.stdout.strip()}")
        elif item["type"] == "image":
            remote_path = f"{DROP_ZONE_ANDROID}/clipboard_image.png"
            if adb("push", item["data"], remote_path, timeout=120).returncode != 0:
                print("[Sync Warning] Failed to push clipboard image over ADB")
                return
            print(f"[Sync] Image pushed to Phone: {os.path.basename(item['data'])}")
            send_android_notification("Nothing Sync", "Clipboard image received")
    except Exception as e:
        print(f"[Error] Android Push Failed: {e}")

def sync_clipboard_to_phone(item):
    """Push a Mac clipboard change to the phone. Prefers the live LAN session
    (instant, no ADB); falls back to the ADB path when no session is active."""
    if item["type"] == "text":
        if push_to_phones({"type": "clip", "format": "text", "data": item["data"]}):
            print(f"[Sync] Text pushed to phone over session ({len(item['data'])} chars)")
            return
    # No live session (or image payload) — fall back to ADB.
    try:
        push_to_android_clipboard(item)
    finally:
        if item["type"] == "image":
            remove_quietly(item["data"])  # temp PNG; one per image copy otherwise piles up

# Native macOS Focus Check
def get_macos_focus_state():
    try:
        res = subprocess.run(
            ["defaults", "read", "com.apple.controlcenter", "NSStatusItem Visible FocusModes"],
            capture_output=True, text=True, timeout=5
        )
        return res.stdout.strip() == "1"
    except:
        return False

def run_adb_connect(address):
    print(f"[ADB] Attempting connection to: {address}")
    res = adb("connect", address, device=False, timeout=20)
    out = res.stdout.strip()
    print(f"[ADB] Result: {out}")
    if "connected to" in out or "already connected to" in out:
        config = load_config()
        config["last_address"] = address
        save_config(config)
        # Setup reverse port forward for real-time cursor/media commands
        adb("-s", address, "reverse", f"tcp:{ADB_REVERSE_PORT}", f"tcp:{LAN_PORT}", device=False)
        print(f"[ADB] Setup reverse port forward tcp:{ADB_REVERSE_PORT} -> tcp:{LAN_PORT}")

def run_adb_connect_safe(address):
    """Thread-safe ADB connect that prevents race conditions between
    Bonjour auto-discovery and the monitor loop (C3)."""
    global adb_connecting
    with adb_connect_lock:
        if adb_connecting:
            print(f"[ADB] Skipping duplicate connect attempt to {address} (already connecting)")
            return
        adb_connecting = True
    try:
        run_adb_connect(address)
    finally:
        with adb_connect_lock:
            adb_connecting = False

def run_adb_pair(address, code):
    print(f"[ADB] Attempting to pair with: {address}")
    proc = subprocess.Popen(
        ["adb", "pair", address],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    try:
        stdout, stderr = proc.communicate(input=f"{code}\n", timeout=15)
        out = (stdout or "").strip() + "\n" + (stderr or "").strip()
        print(f"[ADB Pair Result] {out}")
        if "Successfully paired to" in out:
            return True, out
        else:
            return False, out
    except Exception as e:
        proc.kill()
        return False, str(e)

# Threads for operations
def status_polling_loop():
    # Monitors Focus (Mac -> Android DND sync)
    # Battery polling removed (L4) — Android app sends real-time battery updates via TCP
    last_dnd_state = None
    while True:
        if app_delegate and app_delegate.connected:
            # DND Sync (Mac -> Android): prefer the live session, fall back to ADB
            try:
                dnd_state = get_macos_focus_state()
                if dnd_state != last_dnd_state:
                    last_dnd_state = dnd_state
                    state_str = "on" if dnd_state else "off"
                    if push_to_phones({"type": "dnd", "on": dnd_state}):
                        print(f"[Focus] Pushed Focus Mode '{state_str}' over session")
                    else:
                        adb("shell", f"cmd notification dnd {state_str}")
                        print(f"[Focus] Synced Focus Mode '{state_str}' to Android (ADB)")
            except Exception as e:
                print(f"[Focus] Error syncing DND to Android: {e}")
                
        time.sleep(10)

def mac_clipboard_watcher():
    # Watch Mac clipboard for copy events. changeCount is read here on the worker
    # thread; we only hop to the main thread to read contents when it changes
    # (was: a blocking main-thread round trip 5x a second, forever).
    global CURRENT_CLIPBOARD_CONTENT
    print("[Watcher] Started macOS Clipboard monitor")
    pb = NSPasteboard.generalPasteboard()
    while True:
        try:
            with objc.autorelease_pool():
                if pb.changeCount() != LAST_CHANGE_COUNT:
                    item, count = get_mac_clipboard()
                    if item and item["type"] == "text":
                        with sync_state_lock:
                            is_new = item["data"] != CURRENT_CLIPBOARD_CONTENT
                            if is_new:
                                CURRENT_CLIPBOARD_CONTENT = item["data"]
                        if is_new:
                            db.add_item(item["data"])
                            threading.Thread(target=sync_clipboard_to_phone, args=(item,), daemon=True).start()
                    elif item and item["type"] == "image":
                        threading.Thread(target=sync_clipboard_to_phone, args=(item,), daemon=True).start()
        except Exception as e:
            print(f"[Watcher] Error: {e}")
            time.sleep(1)
        time.sleep(0.2)

# The ADB shell script prints TICK every ~5s; if nothing arrives for this long the
# wireless-ADB link is dead even though `adb shell` hasn't noticed yet.
ADB_STREAM_STALL_TIMEOUT = 30.0

def android_event_monitor():
    global ADB_SERIAL, adb_link_up
    
    # Persistent shell script to monitor clipboard, focus, and files on Android
    # Optimized ADB shell script with differentiated polling intervals (L1, L2):
    # - Clipboard: every 3rd iteration (600ms) — low latency for user-facing sync
    # - Files/DND: every 25th iteration (~5s) — less frequent, reduces ADB overhead
    # Clipboard and DND are seeded silently at start so a reconnect doesn't
    # overwrite the Mac clipboard with a stale phone clip or re-announce DND.
    # Files are read one per line (names may contain spaces); the phone writes
    # dot-prefixed .part files first, which `ls` hides until they're complete.
    shell_script = """
read_clip() {
  data_only=$(cmd clipboard get-text 2>/dev/null | sed -e 's/\r//g')
  if [ -z "$data_only" ]; then
    curr_clip_raw=$(am broadcast -n "TEMPLATE_HELPER_RECEIVER" -a clipper.get -f 32 2>/dev/null | grep "data=")
    temp="${curr_clip_raw#*data=\\"}"
    data_only="${temp%%\\", extras:*}"
    data_only="${data_only%\\"}"
  fi
}
to_mac=/sdcard/Android/data/com.nothing.airshare/files/ToMac
mkdir -p "$to_mac"
read_clip
last_clip="$data_only"
last_zen=$(settings get global zen_mode 2>/dev/null)
last_files=""
count=0
while true; do
  count=$((count + 1))
  if [ $((count % 3)) -eq 0 ]; then
    read_clip
    if [ -n "$data_only" ] && [ "$data_only" != "$last_clip" ]; then
      encoded=$(echo -n "$data_only" | base64 | tr -d "\\r\\n")
      echo "CLIPBOARD:$encoded"
      last_clip="$data_only"
    fi
  fi
  if [ $((count % 25)) -eq 0 ]; then
    echo "TICK"
    curr_zen=$(settings get global zen_mode 2>/dev/null)
    if [ "$curr_zen" != "$last_zen" ]; then
      echo "FOCUS:$curr_zen"
      last_zen="$curr_zen"
    fi
    curr_files=$(ls -1 "$to_mac" 2>/dev/null)
    if [ "$curr_files" != "$last_files" ]; then
      printf '%s\\n' "$curr_files" | while IFS= read -r file; do
        [ -z "$file" ] && continue
        if ! printf '%s\\n' "$last_files" | grep -qxF -- "$file"; then
          echo "FILE:$file"
        fi
      done
      last_files="$curr_files"
    fi
    count=0
  fi
  sleep 0.2
done
"""
    
    reconnect_attempts = 0
    while True:
        try:
            # Check if any ADB devices are connected
            serial = pick_adb_device(list_adb_devices())

            if not serial:
                adb_link_up = False
                refresh_connection_state()
                # A live LAN session already carries clipboard/DND/file over TCP —
                # don't churn ADB reconnects (this was the source of the log spam).
                if has_live_session():
                    reconnect_attempts = 0
                    time.sleep(10)
                    continue
                # Try the saved address with capped exponential backoff, then give
                # up (the wireless-debugging port rotates, so a stale address will
                # never recover — Bonjour re-discovery triggers a fresh connect).
                config = load_config()
                if "last_address" in config and reconnect_attempts < MAX_ADB_RECONNECT_ATTEMPTS:
                    reconnect_attempts += 1
                    backoff = min(10 * (2 ** (reconnect_attempts - 1)), 120)
                    print(f"[ADB] Auto-reconnect {reconnect_attempts}/{MAX_ADB_RECONNECT_ATTEMPTS} "
                          f"to {config['last_address']} (next retry in {backoff}s)")
                    run_adb_connect_safe(config["last_address"])
                    time.sleep(backoff)
                    continue

                time.sleep(15)
                continue

            if serial != ADB_SERIAL:
                print(f"[ADB] Using device {serial}")
            ADB_SERIAL = serial
            reconnect_attempts = 0
            # Setup reverse port forward for real-time cursor/media commands
            adb("reverse", f"tcp:{ADB_REVERSE_PORT}", f"tcp:{LAN_PORT}")
            print(f"[ADB] Setup reverse port forward tcp:{ADB_REVERSE_PORT} -> tcp:{LAN_PORT}")
            if app_delegate:
                model_res = adb("shell", "getprop ro.product.model", timeout=5)
                model = model_res.stdout.strip() if model_res.returncode == 0 else ""
                app_delegate.device_model = model or "Nothing Phone"
            adb_link_up = True
            refresh_connection_state()
                
            # Dynamically detect installed helper package
            detect_helper_package()
            
            # Spawn persistent shell script using base64 encoding to prevent quoting issues
            runnable_script = shell_script.replace("TEMPLATE_HELPER_RECEIVER", HELPER_RECEIVER)
            encoded_script = base64.b64encode(runnable_script.encode('utf-8')).decode('utf-8')
            proc = subprocess.Popen(
                ["adb", "-s", serial, "shell", f"echo {encoded_script} | base64 -d | sh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )

            last_seen = [time.monotonic()]

            def stall_watchdog():
                while proc.poll() is None:
                    time.sleep(5)
                    if time.monotonic() - last_seen[0] > ADB_STREAM_STALL_TIMEOUT:
                        print("[ADB Stream] No heartbeat from phone; restarting stream")
                        proc.kill()
                        return

            threading.Thread(target=stall_watchdog, daemon=True).start()
            
            # Read stdout line-by-line blockingly
            for line in iter(proc.stdout.readline, ""):
                last_seen[0] = time.monotonic()
                line = line.strip().replace('\r', '')
                if not line or line == "TICK":
                    continue
                
                # Handle Clipboard Sync
                if line.startswith("CLIPBOARD:"):
                    encoded_val = line[len("CLIPBOARD:"):]
                    if not encoded_val:
                        continue
                    try:
                        decoded_val = base64.b64decode(encoded_val).decode('utf-8')
                        apply_incoming_clip({"format": "text", "data": decoded_val})
                    except Exception as e:
                        print(f"[Sync] Error decoding Android clipboard: {e}")
                        
                # Handle Focus/DND Sync
                elif line.startswith("FOCUS:"):
                    parts = line.split(":", 1)
                    if len(parts) < 2:
                        continue
                    mode = parts[1]
                    is_dnd = mode != "0"
                    status_text = "Enabled" if is_dnd else "Disabled"
                    print(f"[Android] DND state: {status_text}")
                    send_mac_notification("Nothing Phone", f"Do Not Disturb {status_text}")
                    
                # Handle File Sync (Android -> Mac)
                elif line.startswith("FILE:"):
                    filename = line[len("FILE:"):]
                    if not filename:
                        continue
                    print(f"[Android] New file drop: {filename}")
                    threading.Thread(target=pull_file_from_android, args=(filename,), daemon=True).start()
                else:
                    # Ignore all other output/warnings to keep daemon stable
                    print(f"[ADB Stream Warning] Unexpected line: {line}")
            
            proc.wait()
            print("[ADB Stream] Process exited")
        except Exception as e:
            print(f"[ADB Stream] Connection broke: {e}")
        adb_link_up = False
        refresh_connection_state()
        time.sleep(3)

# Helper to create styled template images for status bar (drawn once, then reused)
_dot_images = {}

def create_template_dot(filled=True):
    if filled in _dot_images:
        return _dot_images[filled]
    img = NSImage.alloc().initWithSize_((16, 16))
    img.setTemplate_(True)
    img.lockFocus()
    NSColor.blackColor().set()
    if filled:
        path = NSBezierPath.bezierPathWithOvalInRect_(((4, 4), (8, 8)))
        path.fill()
    else:
        path = NSBezierPath.bezierPathWithOvalInRect_(((4, 4), (8, 8)))
        path.setLineWidth_(1.5)
        path.stroke()
    img.unlockFocus()
    _dot_images[filled] = img
    return img

def get_current_mac_clipboard_text():
    pb = NSPasteboard.generalPasteboard()
    content = pb.stringForType_(NSStringPboardType)
    return content if content else ""

def push_file_to_android(local_path):
    try:
        send_file_to_phone(local_path, confirm_on_mac=True)
    except Exception as e:
        print(f"[Error] Failed to send {os.path.basename(local_path)}: {e}")
        send_mac_notification("Nothing AirShare Error", f"Failed to send {os.path.basename(local_path)}: {e}")

def trigger_phone_ring():
    print("[Find My Phone] Triggering phone alarm...")
    if push_to_phones({"type": "find_phone"}):
        print("[Find My Phone] Broadcast sent successfully over TCP session.")
        return

    # Explicit component: Android 8+ never delivers implicit broadcasts to
    # manifest receivers, so the old bare `-a clipper.ring` was silently dropped.
    res = adb("shell", f"am broadcast -n {AIRSHARE_RECEIVER} -a clipper.ring -f 32")
    if res.returncode == 0 and "Permission Denial" not in res.stdout + res.stderr:
        print("[Find My Phone] Broadcast sent successfully via ADB fallback.")
    else:
        print(f"[Find My Phone] Error sending broadcast via ADB: {res.stderr.strip() or res.stdout.strip()}")
        send_mac_notification("Nothing AirShare", "Couldn't reach your phone to ring it.")

def run_local_command(cmd_id):
    commands_dict = {
        "lock_screen": "pmset displaysleepnow",
        "screenshot": "screencapture -i ~/Desktop/screenshot_$(date +%Y%m%d_%H%M%S).png",
        "open_terminal": "open -a Terminal",
        "toggle_dark_mode": "osascript -e 'tell app \"System Events\" to tell appearance preferences to set dark mode to not dark mode'",
        "sleep": "pmset sleepnow"
    }
    cmd = commands_dict.get(cmd_id)
    if cmd:
        print(f"[Command] Running: {cmd}")
        subprocess.Popen(cmd, shell=True)
        send_mac_notification("Command Executed", f"Ran command: {cmd_id.replace('_', ' ').title()}")

def show_info_alert(title, text):
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(text)
    alert.addButtonWithTitle_("OK")
    alert.runModal()

def show_accessibility_alert():
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Accessibility Permission Required")
    alert.setInformativeText_(
        "Remote Input features require Accessibility permission to simulate mouse and keyboard events on this Mac.\n\n"
        "Click 'Grant' to open System Settings, then enable Python in the Accessibility list."
    )
    alert.addButtonWithTitle_("Grant Permission")
    alert.addButtonWithTitle_("Later")
    if alert.runModal() == 1000:
        # Prompt OS dialog
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        # Open settings directly
        workspace = NSWorkspace.sharedWorkspace()
        url = NSURL.URLWithString_("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        workspace.openURL_(url)

def show_commands_alert(popover_vc):
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Run Command on Mac")
    alert.setInformativeText_("Select a predefined command to run on this Mac:")
    
    popup = NSPopUpButton.alloc().initWithFrame_(((0, 0), (240, 24)), pullsDown=False)
    commands = [
        ("Lock Screen", "lock_screen"),
        ("Toggle Dark Mode", "toggle_dark_mode"),
        ("Open Terminal", "open_terminal"),
        ("Take Screenshot", "screenshot"),
        ("Put Mac to Sleep", "sleep")
    ]
    for label, cmd_id in commands:
        popup.addItemWithTitle_(label)
        
    alert.setAccessoryView_(popup)
    alert.addButtonWithTitle_("Run")
    alert.addButtonWithTitle_("Cancel")
    
    if alert.runModal() == 1000:
        selected_index = popup.indexOfSelectedItem()
        if 0 <= selected_index < len(commands):
            cmd_label, cmd_id = commands[selected_index]
            run_local_command(cmd_id)

class CardView(NSView):
    def initWithFrame_icon_title_action_(self, frame, icon, title, action):
        self = objc.super(CardView, self).initWithFrame_(frame)
        if self:
            self.icon = icon
            self.title = title
            self.action = action
            self.hovered = False
            self.tracking_area = None
            self.setup_ui()
        return self

    def setup_ui(self):
        self.icon_label = NSTextField.labelWithString_(self.icon)
        self.icon_label.setFont_(NSFont.systemFontOfSize_(24))
        self.icon_label.setFrame_(((0, self.frame().size.height - 45), (self.frame().size.width, 30)))
        self.icon_label.setAlignment_(1) # NSTextAlignmentCenter
        self.icon_label.setTextColor_(NSColor.whiteColor())
        self.icon_label.setEditable_(False)
        self.icon_label.setSelectable_(False)
        self.icon_label.setDrawsBackground_(False)
        self.icon_label.setBezeled_(False)
        self.addSubview_(self.icon_label)

        self.title_label = NSTextField.labelWithString_(self.title)
        self.title_label.setFont_(NSFont.boldSystemFontOfSize_(11))
        self.title_label.setFrame_(((0, 10), (self.frame().size.width, 20)))
        self.title_label.setAlignment_(1) # NSTextAlignmentCenter
        self.title_label.setTextColor_(NSColor.whiteColor())
        self.title_label.setEditable_(False)
        self.title_label.setSelectable_(False)
        self.title_label.setDrawsBackground_(False)
        self.title_label.setBezeled_(False)
        self.addSubview_(self.title_label)

    def drawRect_(self, rect):
        bounds = self.bounds()
        bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.08, 1.0)
        bg_color.setFill()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 12, 12)
        path.fill()
        
        # Border
        if self.hovered:
            border_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(211/255.0, 47/255.0, 47/255.0, 1.0)
            path.setLineWidth_(2.0)
        else:
            border_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.2, 0.2, 1.0)
            path.setLineWidth_(1.0)
            
        border_color.setStroke()
        path.stroke()

    def updateTrackingAreas(self):
        if self.tracking_area:
            self.removeTrackingArea_(self.tracking_area)
        options = 0x01 | 0x10 | 0x20
        self.tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            options,
            self,
            None
        )
        self.addTrackingArea_(self.tracking_area)
        objc.super(CardView, self).updateTrackingAreas()

    def mouseEntered_(self, event):
        self.hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self.hovered = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        if self.action:
            self.action()

class NothingPopoverViewController(NSViewController):
    def init(self):
        print("[PopoverVC] init called")
        self = objc.super(NothingPopoverViewController, self).init()
        if self:
            self.app_delegate = None
            self.button_device_map = {}
            self.button_history_map = {}
            self._last_snapshot = None
        print(f"[PopoverVC] init returning {self}")
        return self

    def loadView(self):
        print("[PopoverVC] loadView called")
        self.main_effect_view = NSVisualEffectView.alloc().initWithFrame_(((0, 0), (360, 530)))
        self.main_effect_view.setMaterial_(4)
        self.main_effect_view.setBlendingMode_(0)
        self.main_effect_view.setState_(1)
        self.main_effect_view.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        
        self.content_view = NSView.alloc().initWithFrame_(((0, 0), (360, 530)))
        self.main_effect_view.addSubview_(self.content_view)
        self.setView_(self.main_effect_view)
        
        print("[PopoverVC] calling setup_ui")
        self.setup_ui()
        print("[PopoverVC] loadView finished")

    def setup_ui(self):
        # Header
        header_bg = NSView.alloc().initWithFrame_(((0, 490), (360, 40)))
        header_bg.setWantsLayer_(True)
        header_bg.layer().setBackgroundColor_(NSColor.blackColor().CGColor())
        
        dot_label = NSTextField.labelWithString_("●")
        dot_label.setFont_(NSFont.boldSystemFontOfSize_(14))
        dot_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(211/255.0, 47/255.0, 47/255.0, 1.0))
        dot_label.setFrame_(((16, 10), (15, 20)))
        header_bg.addSubview_(dot_label)
        
        title_label = NSTextField.labelWithString_("NOTHING AIRSHARE")
        title_label.setFont_(NSFont.boldSystemFontOfSize_(13))
        title_label.setTextColor_(NSColor.whiteColor())
        title_label.setFrame_(((32, 10), (200, 20)))
        header_bg.addSubview_(title_label)
        
        version_label = NSTextField.labelWithString_(f"v{APP_VERSION}")
        version_label.setFont_(NSFont.systemFontOfSize_(10))
        version_label.setTextColor_(NSColor.grayColor())
        version_label.setFrame_(((300, 10), (44, 20)))
        version_label.setAlignment_(2)
        header_bg.addSubview_(version_label)
        
        self.content_view.addSubview_(header_bg)
        
        # Status Card
        self.status_card = NSView.alloc().initWithFrame_(((16, 410), (328, 70)))
        self.status_card.setWantsLayer_(True)
        self.status_card.layer().setCornerRadius_(12)
        self.status_card.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.08, 1.0).CGColor())
        self.status_card.layer().setBorderWidth_(1)
        self.status_card.layer().setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.2, 0.2, 1.0).CGColor())
        
        self.status_dot = NSTextField.labelWithString_("●")
        self.status_dot.setFont_(NSFont.boldSystemFontOfSize_(12))
        self.status_dot.setFrame_(((16, 40), (15, 20)))
        self.status_card.addSubview_(self.status_dot)
        
        self.status_title = NSTextField.labelWithString_("Searching...")
        self.status_title.setFont_(NSFont.boldSystemFontOfSize_(12))
        self.status_title.setTextColor_(NSColor.whiteColor())
        self.status_title.setFrame_(((32, 40), (200, 20)))
        self.status_card.addSubview_(self.status_title)
        
        self.status_subtitle = NSTextField.labelWithString_("Please connect wireless ADB or check Bonjour")
        self.status_subtitle.setFont_(NSFont.systemFontOfSize_(10))
        self.status_subtitle.setTextColor_(NSColor.grayColor())
        self.status_subtitle.setFrame_(((16, 15), (296, 20)))
        self.status_card.addSubview_(self.status_subtitle)
        
        self.content_view.addSubview_(self.status_card)
        
        # Action Cards Grid
        self.card_clipboard = CardView.alloc().initWithFrame_icon_title_action_(
            ((16, 325), (100, 75)), "📋", "Clipboard", self.action_clipboard
        )
        self.card_send = CardView.alloc().initWithFrame_icon_title_action_(
            ((130, 325), (100, 75)), "📁", "Send Files", self.action_send_files
        )
        self.card_remote = CardView.alloc().initWithFrame_icon_title_action_(
            ((244, 325), (100, 75)), "🖱️", "Remote Input", self.action_remote_input
        )
        
        self.card_media = CardView.alloc().initWithFrame_icon_title_action_(
            ((16, 245), (100, 75)), "🎵", "Media", self.action_media
        )
        self.card_find = CardView.alloc().initWithFrame_icon_title_action_(
            ((130, 245), (100, 75)), "📱", "Find Phone", self.action_find_phone
        )
        self.card_commands = CardView.alloc().initWithFrame_icon_title_action_(
            ((244, 245), (100, 75)), "⚙️", "Commands", self.action_commands
        )
        
        self.content_view.addSubview_(self.card_clipboard)
        self.content_view.addSubview_(self.card_send)
        self.content_view.addSubview_(self.card_remote)
        self.content_view.addSubview_(self.card_media)
        self.content_view.addSubview_(self.card_find)
        self.content_view.addSubview_(self.card_commands)
        
        # Nearby Devices Section
        self.devices_section_title = NSTextField.labelWithString_("─── NEARBY DEVICES ───")
        self.devices_section_title.setFont_(NSFont.boldSystemFontOfSize_(9))
        self.devices_section_title.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(211/255.0, 47/255.0, 47/255.0, 1.0))
        self.devices_section_title.setFrame_(((16, 215), (328, 15)))
        self.content_view.addSubview_(self.devices_section_title)
        
        self.devices_container = NSView.alloc().initWithFrame_(((16, 165), (328, 45)))
        self.content_view.addSubview_(self.devices_container)
        
        # Clipboard History Section
        self.clipboard_section_title = NSTextField.labelWithString_("─── CLIPBOARD HISTORY ───")
        self.clipboard_section_title.setFont_(NSFont.boldSystemFontOfSize_(9))
        self.clipboard_section_title.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(211/255.0, 47/255.0, 47/255.0, 1.0))
        self.clipboard_section_title.setFrame_(((16, 140), (328, 15)))
        self.content_view.addSubview_(self.clipboard_section_title)
        
        self.clipboard_container = NSView.alloc().initWithFrame_(((16, 80), (328, 55)))
        self.content_view.addSubview_(self.clipboard_container)
        
        # Bottom Action Buttons
        self.btn_open_folder = NSButton.alloc().initWithFrame_(((16, 40), (158, 32)))
        self.btn_open_folder.setTitle_("Open NothingDrop")
        self.btn_open_folder.setBezelStyle_(NSBezelStyleRounded)
        self.btn_open_folder.setTarget_(self)
        self.btn_open_folder.setAction_("openFolderClicked:")
        self.content_view.addSubview_(self.btn_open_folder)
        
        self.btn_connect_adb = NSButton.alloc().initWithFrame_(((186, 40), (158, 32)))
        self.btn_connect_adb.setTitle_("Connect ADB")
        self.btn_connect_adb.setBezelStyle_(NSBezelStyleRounded)
        self.btn_connect_adb.setTarget_(self)
        self.btn_connect_adb.setAction_("connectAdbClicked:")
        self.content_view.addSubview_(self.btn_connect_adb)
        
        # Quit Button
        self.btn_quit = NSButton.alloc().initWithFrame_(((16, 6), (328, 32)))
        self.btn_quit.setTitle_("Quit Nothing Sync")
        self.btn_quit.setBezelStyle_(NSBezelStyleRounded)
        self.btn_quit.setTarget_(self)
        self.btn_quit.setAction_("quitClicked:")
        self.content_view.addSubview_(self.btn_quit)
        
        self.refresh_data()

    def refresh_data(self, force=False):
        # Runs every 2s while the popover is open; only rebuild when something
        # visible changed instead of tearing down and recreating every row.
        delegate = self.app_delegate
        devices = list(bonjour_manager.discovered_devices) if bonjour_manager else []
        history = db.get_history() if db else []
        snapshot = (
            bool(delegate and delegate.connected),
            getattr(delegate, "battery_level", None), getattr(delegate, "charging", None),
            getattr(delegate, "device_model", None), tuple(devices[:3]), tuple(history[:3]),
        )
        if snapshot == self._last_snapshot and not force:
            return
        self._last_snapshot = snapshot

        # Clear stale button maps to prevent memory leaks (M4)
        self.button_device_map.clear()
        self.button_history_map.clear()
        # Update Status Card
        if self.app_delegate and self.app_delegate.connected:
            self.status_dot.setTextColor_(NSColor.greenColor())
            self.status_title.setStringValue_("Connected")
            
            battery = self.app_delegate.battery_level
            charging_str = " (Charging)" if self.app_delegate.charging else ""
            device_model = getattr(self.app_delegate, "device_model", "Nothing Phone")
            self.status_subtitle.setStringValue_(f"{device_model}  ·  Battery {battery}%{charging_str}")
        else:
            self.status_dot.setTextColor_(NSColor.redColor())
            self.status_title.setStringValue_("Searching...")
            self.status_subtitle.setStringValue_("Please connect wireless ADB or check Bonjour")
            
        # Update Nearby Devices
        for subview in list(self.devices_container.subviews()):
            subview.removeFromSuperview()
            
        y_offset = 25
        if not devices:
            lbl = NSTextField.labelWithString_("No nearby sharing devices found")
            lbl.setFont_(NSFont.systemFontOfSize_(11))
            lbl.setTextColor_(NSColor.grayColor())
            lbl.setFrame_(((0, y_offset), (328, 18)))
            self.devices_container.addSubview_(lbl)
        else:
            for name in devices[:3]:  # Show up to 3 nearby devices (M3)
                row_view = NSView.alloc().initWithFrame_(((0, y_offset), (328, 20)))
                device_lbl = NSTextField.labelWithString_(f"📱 {name}")
                device_lbl.setFont_(NSFont.systemFontOfSize_(12))
                device_lbl.setTextColor_(NSColor.whiteColor())
                device_lbl.setFrame_(((0, 0), (200, 20)))
                row_view.addSubview_(device_lbl)
                
                btn = NSButton.alloc().initWithFrame_(((240, -4), (88, 24)))
                btn.setTitle_("Send File")
                btn.setBezelStyle_(NSBezelStyleRounded)
                btn.setTarget_(self)
                btn.setAction_("sendToNearbyDevice:")
                self.button_device_map[btn] = name
                row_view.addSubview_(btn)
                
                self.devices_container.addSubview_(row_view)
                y_offset -= 22
                
        # Update Clipboard History
        for subview in list(self.clipboard_container.subviews()):
            subview.removeFromSuperview()
            
        y_offset = 32
        if not history:
            lbl = NSTextField.labelWithString_("Clipboard history is empty")
            lbl.setFont_(NSFont.systemFontOfSize_(11))
            lbl.setTextColor_(NSColor.grayColor())
            lbl.setFrame_(((0, y_offset), (328, 18)))
            self.clipboard_container.addSubview_(lbl)
        else:
            for text in history[:3]:  # Show 3 clipboard history items as documented in README (M2)
                display_text = text.replace('\n', ' ')
                if len(display_text) > 42:
                    display_text = display_text[:39] + "..."
                    
                row_btn = NSButton.alloc().initWithFrame_(((0, y_offset), (328, 20)))
                row_btn.setButtonType_(0)
                row_btn.setBezelStyle_(1)
                row_btn.setBordered_(False)
                row_btn.setTitle_(f"● {display_text}")
                row_btn.setFont_(NSFont.systemFontOfSize_(11))
                row_btn.setAlignment_(0)
                
                attr_title = NSMutableAttributedString.alloc().initWithString_attributes_(
                    f"● {display_text}",
                    {
                        NSForegroundColorAttributeName: NSColor.lightGrayColor(),
                        NSFontAttributeName: NSFont.systemFontOfSize_(11)
                    }
                )
                row_btn.setAttributedTitle_(attr_title)
                
                row_btn.setTarget_(self)
                row_btn.setAction_("historyItemClicked:")
                self.button_history_map[row_btn] = text
                
                self.clipboard_container.addSubview_(row_btn)
                y_offset -= 22

    @objc.IBAction
    def historyItemClicked_(self, sender):
        print(f"[PopoverVC] historyItemClicked_ called with sender {sender}")
        text = self.button_history_map.get(sender)
        if text:
            set_mac_clipboard("text", text)
            send_mac_notification("Clipboard Restored", f"Restored: {text[:30]}")
            self.refresh_data()
            if self.app_delegate and self.app_delegate.connected:
                threading.Thread(target=sync_clipboard_to_phone, args=({"type": "text", "data": text},), daemon=True).start()

    @objc.IBAction
    def sendToNearbyDevice_(self, sender):
        print(f"[PopoverVC] sendToNearbyDevice_ called with sender {sender}")
        device_name = self.button_device_map.get(sender)
        if device_name and self.app_delegate:
            fake_sender = NSObject.alloc().init()
            fake_sender.representedObject = lambda: device_name
            self.app_delegate.sendFileToDevice_(fake_sender)

    @objc.IBAction
    def openFolderClicked_(self, sender):
        print(f"[PopoverVC] openFolderClicked_ called with sender {sender}")
        if self.app_delegate:
            self.app_delegate.openNothingDrop_(sender)

    @objc.IBAction
    def connectAdbClicked_(self, sender):
        print(f"[PopoverVC] connectAdbClicked_ called with sender {sender}")
        if self.app_delegate:
            self.app_delegate.connectADB_(sender)

    @objc.IBAction
    def quitClicked_(self, sender):
        print(f"[PopoverVC] quitClicked_ called with sender {sender}")
        if self.app_delegate:
            self.app_delegate.quitApp_(sender)

    def action_clipboard(self):
        clip_text = get_current_mac_clipboard_text()
        if clip_text:
            send_mac_notification("Nothing Clipboard", "Syncing clipboard to phone...")
            threading.Thread(target=sync_clipboard_to_phone, args=({"type": "text", "data": clip_text},), daemon=True).start()
        else:
            send_mac_notification("Nothing Clipboard", "Mac clipboard is empty.")

    def action_send_files(self):
        if self.app_delegate and self.app_delegate.connected:
            from AppKit import NSOpenPanel
            panel = NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(True)
            panel.setCanChooseDirectories_(False)
            panel.setAllowsMultipleSelection_(False)
            if panel.runModal() == 1:
                file_path = panel.URL().path()
                if file_path:
                    send_mac_notification("Nothing AirShare", f"Sending {os.path.basename(file_path)}...")
                    threading.Thread(target=push_file_to_android, args=(file_path,), daemon=True).start()
        else:
            send_mac_notification("Nothing AirShare", "No connected phone. Connect via ADB first.")

    def action_remote_input(self):
        if AXIsProcessTrusted():
            show_info_alert(
                "Remote Input Active",
                "Accessibility permission is granted. To control this Mac, open 'Nothing AirShare' on your Nothing Phone, tap 'Remote Input' and use the trackpad surface."
            )
        else:
            show_accessibility_alert()

    def action_media(self):
        show_info_alert(
            "Media Control",
            "To control media/volume on this Mac, open 'Nothing AirShare' on your Nothing Phone, tap 'Media Remote' and use the play, pause, next, and previous buttons."
        )

    def action_find_phone(self):
        if self.app_delegate and self.app_delegate.connected:
            send_mac_notification("Nothing Phone", "Triggering alarm on your Nothing Phone...")
            threading.Thread(target=trigger_phone_ring, daemon=True).start()
        else:
            send_mac_notification("Nothing AirShare", "Phone not connected. Cannot find phone.")

    def action_commands(self):
        show_commands_alert(self)

# App startup logic
class ApplicationBootstrap(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        global app_delegate, db, bonjour_manager
        
        # Instantiate history database
        db = ClipboardHistoryDB()
        
        # Instantiate and start Bonjour Manager
        bonjour_manager = BonjourManager.alloc().init()
        bonjour_manager.start()

        # Start P2P TCP Server
        threading.Thread(target=mac_tcp_server_loop, daemon=True).start()
        
        # Setup Status Bar
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        button.setImage_(create_template_dot(filled=False))
        button.setImagePosition_(2) # NSImageLeft
        
        app_delegate = self
        self.connected = False
        self.battery_level = "--"
        self.charging = False
        self.device_model = "Nothing Phone"
        
        # Create Popover and Popover ViewController
        self.popover = NSPopover.alloc().init()
        self.popover.setBehavior_(1) # NSPopoverBehaviorTransient
        self.popover.setContentSize_((360, 530))
        
        self.popover_vc = NothingPopoverViewController.alloc().init()
        self.popover_vc.app_delegate = self
        self.popover.setContentViewController_(self.popover_vc)
        
        # Attach an empty NSMenu with delegate — the ONLY reliable way to detect
        # status bar clicks in pyobjc on modern macOS. Button setAction_/setTarget_
        # does NOT work because pyobjc processes don't receive status bar button
        # action messages. Instead, we intercept menuWillOpen_ to show our popover.
        self._status_menu = NSMenu.alloc().init()
        self._status_menu.setDelegate_(self)
        self.status_item.setMenu_(self._status_menu)
        
        # Build default menu UI
        self.updateUIOnMainThread()
        
        # Start background threads
        threading.Thread(target=android_event_monitor, daemon=True).start()
        threading.Thread(target=mac_clipboard_watcher, daemon=True).start()
        threading.Thread(target=status_polling_loop, daemon=True).start()
        threading.Thread(target=heartbeat_loop, daemon=True).start()
        
        # Start file watchdog on macOS Drop folder and Downloads folder for AirDrop forwarding
        observer = Observer()
        observer.schedule(MacDropHandler(), DROP_ZONE_MAC, recursive=False)
        downloads_dir = os.path.expanduser("~/Downloads")
        if os.path.exists(downloads_dir):
            observer.schedule(DownloadsAirDropHandler(), downloads_dir, recursive=False)
        observer.start()

    def set_connected(self, val):
        if self.connected == val:
            return
        self.connected = val
        self.update_menu()

    def update_battery_level_charging(self, level, charging):
        # Deduplicate battery updates — only update if value actually changed (M5)
        new_level = str(level)
        if new_level == self.battery_level and charging == self.charging:
            return
        self.battery_level = new_level
        self.charging = charging
        self.update_menu()

    def update_menu(self):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "updateUIOnMainThread", None, False
        )

    # NSMenuDelegate: intercept menu open to show popover instead
    @objc.signature(b'v@:@')
    def menuWillOpen_(self, menu):
        print("[MenuDelegate] menuWillOpen_ called!")
        # Cancel the (empty) menu from actually appearing
        menu.cancelTracking()
        # Toggle the popover
        self._togglePopover()

    def _togglePopover(self):
        print("[Popover] _togglePopover called!")
        button = self.status_item.button()
        print(f"[Popover] Is shown? {self.popover.isShown()}")
        if self.popover.isShown():
            self.popover.performClose_(None)
            # Stop auto-refresh timer when popover closes (M1)
            self._stopRefreshTimer()
        else:
            # Activate the app so the popover can become key window
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            if self.popover_vc.isViewLoaded():
                try:
                    self.popover_vc.refresh_data()
                except Exception as e:
                    import traceback
                    print(f"[Popover] Error in refresh_data: {e}")
                    traceback.print_exc()
            else:
                print("[Popover] View controller view not loaded yet, skipping pre-refresh")
            print("[Popover] Showing popover relative to status bar button...")
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                button.bounds(),
                button,
                1 # NSMinYEdge
            )
            try:
                self.popover.contentViewController().view().window().makeKeyWindow()
                print("[Popover] Popover window made key window.")
            except Exception as e:
                print(f"[Popover] Error making window key: {e}")
            # Start auto-refresh timer while popover is open (M1)
            self._startRefreshTimer()

    def _startRefreshTimer(self):
        """Start a 2-second repeating timer to auto-refresh popover data (M1)."""
        from Foundation import NSTimer, NSRunLoop, NSDefaultRunLoopMode
        if hasattr(self, '_refresh_timer') and self._refresh_timer:
            self._refresh_timer.invalidate()
        self._refresh_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, self, "_refreshTimerFired:", None, True
        )
        print("[Popover] Auto-refresh timer started (2s interval)")

    def _stopRefreshTimer(self):
        """Stop the popover auto-refresh timer."""
        if hasattr(self, '_refresh_timer') and self._refresh_timer:
            self._refresh_timer.invalidate()
            self._refresh_timer = None
            print("[Popover] Auto-refresh timer stopped")

    def _refreshTimerFired_(self, timer):
        """Called by NSTimer every 2 seconds while popover is open."""
        if self.popover.isShown() and self.popover_vc.isViewLoaded():
            try:
                self.popover_vc.refresh_data()
            except Exception as e:
                print(f"[Popover] Auto-refresh error: {e}")
        else:
            self._stopRefreshTimer()

    def updateUIOnMainThread(self):
        if self.connected:
            battery_str = f" {self.battery_level}%"
            if self.charging:
                battery_str += " ⚡️"
            self.status_item.button().setTitle_(battery_str)
            self.status_item.button().setImage_(create_template_dot(filled=True))
        else:
            self.status_item.button().setTitle_("")
            self.status_item.button().setImage_(create_template_dot(filled=False))
            
        if self.popover.isShown():
            self.popover_vc.refresh_data()

    def restoreClipboard_(self, sender):
        text = sender.representedObject()
        if text:
            set_mac_clipboard("text", text)
            print(f"[UI] Restored from history ({len(text)} chars)")

    def sendFileToDevice_(self, sender):
        device_name = sender.representedObject()
        if not device_name or not bonjour_manager or device_name not in bonjour_manager.discovered_devices:
            return
            
        host, port = bonjour_manager.discovered_devices[device_name]
        
        # Open file dialog on macOS main thread
        from AppKit import NSOpenPanel
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        
        if panel.runModal() == 1:  # NSModalResponseOK
            url = panel.URL()
            file_path = url.path()
            if file_path:
                threading.Thread(
                    target=mac_send_file_to_peer, 
                    args=(file_path, device_name, host, port), 
                    daemon=True
                ).start()

    def airdropLastFile_(self, sender):
        global LAST_PULLED_FILE
        if LAST_PULLED_FILE and os.path.exists(LAST_PULLED_FILE):
            url = NSURL.fileURLWithPath_(LAST_PULLED_FILE)
            service = NSSharingService.sharingServiceNamed_(NSSharingServiceNameSendViaAirDrop)
            if service:
                service.performWithItems_([url])
                print(f"[AirDrop] Shared last pulled file with iOS/AirDrop: {LAST_PULLED_FILE}")

    def openNothingDrop_(self, sender):
        print("[AppBootstrap] openNothingDrop_ called!")
        workspace = NSWorkspace.sharedWorkspace()
        url = NSURL.fileURLWithPath_(DROP_ZONE_MAC)
        workspace.openURL_(url)

    def connectADB_(self, sender):
        print("[AppBootstrap] connectADB_ called!")
        threading.Thread(target=self.show_connect_dialog, daemon=True).start()

    def installHelper_(self, sender):
        threading.Thread(target=self.run_install_helper, daemon=True).start()

    def run_install_helper(self):
        local_apk_path = os.path.expanduser("~/.nothing_sync/NothingAirShare.apk")
        
        # 1. Check if APK exists locally
        if not os.path.exists(local_apk_path):
            print("[Helper Install Error] Custom NothingAirShare.apk not found at " + local_apk_path)
            send_mac_notification(
                "Build Required", 
                "NothingAirShare.apk not found. Please run build_apk.sh first."
            )
            return
            
        try:
            # 2. Install via ADB
            send_mac_notification("Nothing AirShare", "Installing APK on Phone...")
            print("[Helper Install] Installing custom APK on phone: " + local_apk_path)
            
            # Accept ADB installs bypass settings first to ensure smooth installation
            adb("shell", "settings put global verifier_verify_adb_installs 0")
            
            res = adb("install", "-r", local_apk_path, timeout=300)
            
            if res.returncode == 0:
                print("[Helper Install] Successfully installed custom APK on phone.")
                send_mac_notification(
                    "Nothing AirShare Success", 
                    "Successfully installed! Please open 'Nothing AirShare' on your phone once to activate."
                )
            else:
                error_msg = res.stderr.strip() or res.stdout.strip()
                print("[Helper Install Error] ADB Install failed: " + error_msg)
                send_mac_notification("Nothing AirShare Error", "Install failed: " + error_msg)
        except Exception as e:
            print("[Helper Install Error] Exception: " + str(e))
            send_mac_notification("Nothing AirShare Error", "Failed to install: " + str(e))

    def show_connect_dialog(self):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "runConnectDialogOnMainThread", None, True
        )

    def runConnectDialogOnMainThread(self):
        # Close popover to prevent focus conflicts and activate app
        if hasattr(self, 'popover') and self.popover.isShown():
            self.popover.performClose_(None)
            
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        
        from AppKit import NSAlert, NSTextField
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Connect or Pair ADB Wireless")
        alert.setInformativeText_(
            "If your Nothing Phone is not paired with this Mac yet, click 'Pair Device' first.\n"
            "Otherwise, enter the Wireless Debugging IP & Port (e.g. 192.168.x.x:4XXXX) and click 'Connect':"
        )
        alert.addButtonWithTitle_("Connect")
        alert.addButtonWithTitle_("Pair Device")
        alert.addButtonWithTitle_("Cancel")
        
        # Pre-fill discovered address if available
        default_address = ""
        if bonjour_manager and bonjour_manager.discovered_devices:
            for name, (host, port) in bonjour_manager.discovered_devices.items():
                if "adb" in name.lower() or "connect" in name.lower():
                    default_address = f"{host}:{port}"
                    break
        if not default_address:
            config = load_config()
            default_address = config.get("last_address", "")
            
        input_field = NSTextField.alloc().initWithFrame_(((0, 0), (240, 24)))
        input_field.setPlaceholderString_("192.168.1.100:5555")
        input_field.setStringValue_(default_address)
        alert.setAccessoryView_(input_field)
        
        response = alert.runModal()
        if response == 1000:  # Connect
            address = input_field.stringValue()
            if address:
                config = load_config()
                config["last_address"] = address
                save_config(config)
                threading.Thread(target=run_adb_connect, args=(address,), daemon=True).start()
        elif response == 1001:  # Pair Device
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "runPairDialogOnMainThread", None, False
            )

    def runPairDialogOnMainThread(self):
        from AppKit import NSAlert, NSTextField, NSView
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Pair Device via ADB")
        alert.setInformativeText_(
            "1. On your phone, go to 'Developer Options' -> 'Wireless debugging'.\n"
            "2. Tap 'Pair device with pairing code'.\n"
            "3. Enter the pairing IP & Port and the 6-digit Wi-Fi pairing code below:"
        )
        alert.addButtonWithTitle_("Pair")
        alert.addButtonWithTitle_("Cancel")
        
        container = NSView.alloc().initWithFrame_(((0, 0), (280, 60)))
        
        ip_field = NSTextField.alloc().initWithFrame_(((0, 32), (280, 24)))
        ip_field.setPlaceholderString_("Pairing IP & Port (e.g. 192.168.x.x:4XXXX)")
        
        # Pre-fill discovered IP
        default_ip = ""
        if bonjour_manager and bonjour_manager.discovered_devices:
            for name, (host, port) in bonjour_manager.discovered_devices.items():
                if "adb" in name.lower() or "connect" in name.lower():
                    default_ip = f"{host}:"
                    break
        if not default_ip:
            config = load_config()
            last_addr = config.get("last_address", "")
            if last_addr and ":" in last_addr:
                default_ip = f"{last_addr.split(':')[0]}:"
        ip_field.setStringValue_(default_ip)
        
        code_field = NSTextField.alloc().initWithFrame_(((0, 0), (140, 24)))
        code_field.setPlaceholderString_("Pairing Code")
        
        container.addSubview_(ip_field)
        container.addSubview_(code_field)
        alert.setAccessoryView_(container)
        
        response = alert.runModal()
        if response == 1000:  # Pair
            address = ip_field.stringValue()
            code = code_field.stringValue()
            if address and code:
                threading.Thread(target=self.run_adb_pair_bg, args=(address, code), daemon=True).start()

    def run_adb_pair_bg(self, address, code):
        print(f"[ADB] Pairing with {address}...")
        send_mac_notification("Nothing AirShare", f"Pairing with {address}...")
        success, out = run_adb_pair(address, code)
        if success:
            print(f"[ADB] Pairing success: {out}")
            send_mac_notification("Nothing AirShare Success", "Devices successfully paired! You can now Connect.")
        else:
            print(f"[ADB] Pairing failed: {out}")
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "showPairError:", f"Pairing failed:\n{out}", False
            )

    def showPairError_(self, message):
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Pairing Failed")
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    def quitApp_(self, sender):
        print("[AppBootstrap] quitApp_ called!")
        NSApplication.sharedApplication().terminate_(None)

class RotatingLog:
    """stdout/stderr replacement for the bundled .app, which has no console (all
    print() output used to vanish). Timestamps lines and keeps one backup."""

    def __init__(self, path, max_bytes):
        self.path = path
        self.max_bytes = max_bytes
        self.lock = threading.Lock()
        self.at_line_start = True
        self.f = open(path, "a", encoding="utf-8", errors="replace")

    def write(self, text):
        with self.lock:
            if self.at_line_start and text not in ("\n", ""):
                self.f.write(time.strftime("%m-%d %H:%M:%S "))
            self.f.write(text)
            self.at_line_start = text.endswith("\n")
            self.f.flush()
            if self.at_line_start and self.f.tell() > self.max_bytes:
                self.f.close()
                os.replace(self.path, self.path + ".1")
                self.f = open(self.path, "a", encoding="utf-8", errors="replace")
        return len(text)

    def flush(self):
        with self.lock:
            self.f.flush()

    def isatty(self):
        return False


def setup_logging():
    if sys.stdout is not None and sys.stdout.isatty():
        return  # running from a terminal: keep printing there
    try:
        sys.stdout = sys.stderr = RotatingLog(LOG_FILE, LOG_MAX_BYTES)
    except OSError as e:
        print(f"[Log] Could not open {LOG_FILE}: {e}")


_instance_lock_file = None

def acquire_single_instance_lock():
    """Refuse to start a second copy (e.g. the .app plus the legacy launchd agent):
    two daemons fight over port 53317 and keep restarting each other's adb server."""
    global _instance_lock_file
    try:
        _instance_lock_file = open(os.path.join(CONFIG_DIR, "daemon.lock"), "w")
        fcntl.flock(_instance_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def main():
    setup_logging()
    print(f"===== Nothing AirShare v{APP_VERSION} starting =====")
    if not acquire_single_instance_lock():
        print("[Startup] Another Nothing AirShare instance is already running; exiting.")
        send_mac_notification("Nothing AirShare", "Already running — look for the dot in your menu bar.", wait=True)
        return

    # Disable ADB's built-in mDNS to prevent duplicate device connections
    os.environ["ADB_MDNS"] = "0"
    adb("kill-server", device=False, timeout=10)
    if adb("start-server", device=False, timeout=20).returncode != 0:
        print("[ADB Init Warning] Failed to restart ADB server")

    app = NSApplication.sharedApplication()
    # Set as accessory app (menu bar only, no Dock icon, no main window)
    from AppKit import NSApplicationActivationPolicyAccessory
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = ApplicationBootstrap.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    main()
