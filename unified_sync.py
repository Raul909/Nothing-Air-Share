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
    NSFontAttributeName
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

def simulate_media_key(key):
    try:
        if not _ax_ok(): return
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
DROP_ZONE_MAC = os.path.expanduser("~/NothingDrop")
DROP_ZONE_ANDROID = "/sdcard/Download/NothingDrop"
TEMP_DIR = os.path.expanduser("~/.nothing_sync_temp")
CONFIG_DIR = os.path.expanduser("~/.nothing_sync")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DB_FILE = os.path.join(CONFIG_DIR, "history.db")

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
            with self.write_lock:
                self.conn.sendall(struct.pack('!I', len(payload)))
                self.conn.sendall(payload)
            return True
        except Exception as e:
            print(f"[Session] Send to {self.name} failed: {e}")
            self.close()
            return False

    def close(self):
        self.alive = False
        unregister_session(self)


def register_session(session):
    with peer_sessions_lock:
        peer_sessions[session.name] = session
    print(f"[Session] Registered live session with {session.name}")
    if app_delegate:
        app_delegate.set_connected(True)


def unregister_session(session):
    removed = False
    with peer_sessions_lock:
        if peer_sessions.get(session.name) is session:
            del peer_sessions[session.name]
            removed = True
        any_left = bool(peer_sessions)
    if removed:
        print(f"[Session] Closed session with {session.name}")
    if not any_left and app_delegate:
        app_delegate.set_connected(False)


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
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('0.0.0.0', LAN_PORT))
        server.listen(5)
        print(f"[TCP Server] Listening for peer transfers and commands on port {LAN_PORT}")
    except Exception as e:
        print(f"[TCP Server] Bind failed: {e}")
        return

    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_mac_incoming_connection, args=(conn,), daemon=True).start()
        except Exception as e:
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
                print(f"[TCP Server] Received command: {data}")

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


def handle_incoming_file_data(conn, metadata):
    try:
        sender = metadata.get("senderName", "Unknown Device")
        filename = metadata.get("fileName", "file.bin")
        filesize = metadata.get("fileSize", 0)
        provided_pin = metadata.get("pin", "")

        config = load_config()
        expected_pin = config.get("security_pin", "1234")
        if provided_pin != expected_pin:
            print("[P2P Receiver] Unauthorized transfer attempt (Invalid PIN)")
            conn.send(bytes([0x02]))
            return

        print(f"[P2P Receiver] Incoming file request from {sender}: {filename} ({filesize} bytes)")

        # 3. Prompt user via AppleScript
        size_mb = filesize / 1024.0 / 1024.0
        prompt_script = f'''
        tell application "System Events"
            activate
            display dialog "Incoming file share from {sender}\n\nFile: {filename}\nSize: {size_mb:.2f} MB\n\nDo you want to accept this file?" with title "Nothing AirShare" buttons {{"Decline", "Accept"}} default button "Accept"
        end tell
        '''
        proc = subprocess.run(["osascript", "-e", prompt_script], capture_output=True, text=True)
        accepted = "Accept" in proc.stdout

        # 4. Respond with approval code
        if accepted:
            conn.send(bytes([0x01]))  # Accept
            print("[P2P Receiver] User accepted the transfer. Receiving stream...")
            send_mac_notification("Nothing AirShare", f"Receiving '{filename}' from {sender}...")

            # 5. Receive stream
            dest_dir = DROP_ZONE_MAC
            dest_path = os.path.join(dest_dir, filename)

            # Prevent file collisions
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                counter += 1

            with open(dest_path, 'wb') as f:
                received = 0
                while received < filesize:
                    to_read = min(262144, filesize - received)  # 256KB buffer (L5)
                    chunk = conn.recv(to_read)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)

            print(f"[P2P Receiver] Successfully received: {dest_path}")
            
            # Import to macOS Spotlight index and notify
            subprocess.run(["mdimport", dest_path], capture_output=True)
            send_mac_notification("Nothing AirShare Success", f"Received '{os.path.basename(dest_path)}' from {sender}")
        else:
            conn.send(bytes([0x02]))  # Decline
            print("[P2P Receiver] User declined the transfer.")
    except Exception as e:
        print(f"[P2P Receiver Error] Connection failed: {e}")


def mac_send_file_to_peer(file_path, device_name, host, port):
    try:
        send_mac_notification("Nothing AirShare", f"Connecting to {device_name}...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30.0)
        sock.connect((host, port))

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

            # 3. Stream data
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    sock.sendall(chunk)

            print(f"[P2P Sender] Sent {filename} to {device_name}")
            send_mac_notification("Nothing AirShare Success", f"Sent '{filename}' to {device_name} successfully!")
        else:
            send_mac_notification("Nothing AirShare", f"{device_name} declined the transfer request.")

    except Exception as e:
        print(f"[P2P Sender Error] Transfer failed: {e}")
        send_mac_notification("Nothing AirShare Error", f"Failed to send: {e}")
    finally:
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
            
        print(f"[AirDrop Forwarder] Detected iOS AirDropped file: {filename}")
        send_mac_notification("AirDrop Forwarder", f"Forwarding iOS AirDrop to Nothing Phone: {filename}")
        
        # Wait for file write to complete
        try:
            if not os.path.exists(filepath):
                return
            size1 = os.path.getsize(filepath)
            time.sleep(0.5)
            if not os.path.exists(filepath):
                return
            size2 = os.path.getsize(filepath)
            while size1 != size2:
                size1 = size2
                time.sleep(0.5)
                if not os.path.exists(filepath):
                    return
                size2 = os.path.getsize(filepath)
                
            # Push to phone over ADB
            remote_path = f"{DROP_ZONE_ANDROID}/{filename}"
            subprocess.run(["adb", "shell", f"mkdir -p {DROP_ZONE_ANDROID}"], check=True, capture_output=True)
            res = subprocess.run(["adb", "push", filepath, remote_path], check=True, capture_output=True)
            if res.returncode == 0:
                print(f"[AirDrop Forwarder] Successfully forwarded to Phone: {filename}")
                send_android_notification("Nothing Drop", f"Received from iOS: {filename}")
        except Exception as e:
            print(f"[AirDrop Forwarder Error] Failed to forward {filename}: {e}")

    def is_airdrop_file(self, filepath):
        try:
            if not os.path.exists(filepath):
                return False
            # Run xattr -p com.apple.quarantine to check if agent is AirDrop
            res = subprocess.run(["xattr", "-p", "com.apple.quarantine", filepath], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and "AirDrop" in res.stdout:
                return True
        except Exception:
            pass
        return False


# SQLite Clipboard History helper
class ClipboardHistoryDB:
    def __init__(self):
        self.db_path = DB_FILE
        self.init_db()

    def init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT NOT NULL,
                        timestamp REAL NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"[DB Error] Init failed: {e}")

    def add_item(self, content):
        if not content or len(content.strip()) == 0:
            return
        if len(content) > 10000:  # Skip storing extremely long text/data
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT content FROM history ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                if row and row[0] == content:
                    return
                cursor.execute("INSERT INTO history (content, timestamp) VALUES (?, ?)", (content, time.time()))
                # Keep last 50
                cursor.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 50)")
                conn.commit()
        except Exception as e:
            print(f"[DB Error] Insert failed: {e}")

    def get_history(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT content FROM history ORDER BY id DESC LIMIT 10")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"[DB Error] Fetch failed: {e}")
            return []

# Notification Helpers
def send_mac_notification(title, message):
    try:
        escaped_title = title.replace('"', '\\"')
        escaped_msg = message.replace('"', '\\"')
        script = f'display notification "{escaped_msg}" with title "{escaped_title}"'
        subprocess.run(["osascript", "-e", script], capture_output=True)
    except Exception as e:
        print(f"[Notification] Failed to send macOS notification: {e}")

def send_android_notification(title, message):
    try:
        escaped_title = title.replace("'", "'\\''")
        escaped_msg = message.replace("'", "'\\''")
        subprocess.run([
            "adb", "shell",
            f"cmd notification post -S bigtext -t '{escaped_title}' 'nothing_sync' '{escaped_msg}'"
        ], capture_output=True)
    except Exception as e:
        print(f"[Notification] Failed to send Android notification: {e}")

# Smart File Routing and Spotlight Import
def pull_file_from_android(filename):
    remote_path = f"/sdcard/Android/data/com.nothing.airshare/files/ToMac/{filename}"
    temp_local_path = os.path.join(TEMP_DIR, filename)
    
    try:
        # Pull file to temp folder first to avoid half-written files
        res = subprocess.run(["adb", "pull", remote_path, temp_local_path], capture_output=True, timeout=60)
        if res.returncode != 0:
            print(f"[Drop] Failed to pull {filename}: {res.stderr.decode()}")
            return
            
        # Delete from Android
        subprocess.run(["adb", "shell", f"rm \"{remote_path}\""], capture_output=True)
        
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
        final_path = os.path.join(dest_dir, filename)
        
        # Prevent file overwrite by appending suffix
        base, extension = os.path.splitext(filename)
        counter = 1
        while os.path.exists(final_path):
            final_path = os.path.join(dest_dir, f"{base}_{counter}{extension}")
            counter += 1
            
        shutil.move(temp_local_path, final_path)
        print(f"[Drop] Pulled and routed {filename} to {final_path}")
        
        # Import to macOS Spotlight index
        subprocess.run(["mdimport", final_path], capture_output=True)
        
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

# File Drop Handler (Mac -> Android)
class MacDropHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            filename = os.path.basename(event.src_path)
            if filename.startswith('.'):
                return
            print(f"[Drop] New local file detected: {filename}")
            threading.Thread(target=self.push_to_android, args=(event.src_path,)).start()
            
    def push_to_android(self, local_path):
        filename = os.path.basename(local_path)
        remote_path = f"{DROP_ZONE_ANDROID}/{filename}"
        try:
            # Let file writing finish on Mac
            size1 = os.path.getsize(local_path)
            time.sleep(0.5)
            size2 = os.path.getsize(local_path)
            while size1 != size2:
                size1 = size2
                time.sleep(0.5)
                size2 = os.path.getsize(local_path)
                
            subprocess.run(["adb", "shell", f"mkdir -p {DROP_ZONE_ANDROID}"], check=True, capture_output=True)
            res = subprocess.run(["adb", "push", local_path, remote_path], check=True, capture_output=True)
            if res.returncode == 0:
                print(f"[Sync] Pushed to Phone: {filename}")
                send_android_notification("Nothing Drop", f"Received: {filename}")
        except Exception as e:
            print(f"[Error] Failed to push {filename}: {e}")

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
        
        # 1. Check for Files
        if pb.availableTypeFromArray_([NSFilenamesPboardType]):
            files = pb.propertyListForType_(NSFilenamesPboardType)
            if files:
                context['result'] = ({"type": "file", "data": files[0]}, change_count)
                return
            
        # 2. Check for Images
        if pb.availableTypeFromArray_([NSTIFFPboardType]):
            image_data = pb.dataForType_(NSPNGFileType)
            if not image_data:
                image = NSImage.alloc().initWithPasteboard_(pb)
                if image:
                    tiff_data = image.TIFFRepresentation()
                    bitmap = NSBitmapImageRep.imageRepWithData_(tiff_data)
                    image_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
            
            if image_data:
                temp_path = os.path.join(TEMP_DIR, f"clip_img_{int(time.time())}.png")
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
        if text != CURRENT_CLIPBOARD_CONTENT:
            print(f"[Phone] Clipboard changed: {text[:20]}...")
            CURRENT_CLIPBOARD_CONTENT = text
            if db:
                db.add_item(text)
            set_mac_clipboard("text", text)
            send_mac_notification("Nothing Clipboard", f"Copied: {text[:30]}")

def detect_helper_package():
    global HELPER_PACKAGE, HELPER_RECEIVER
    try:
        res = subprocess.run(["adb", "shell", "pm list packages"], capture_output=True, text=True, timeout=5)
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
            escaped_text = item["data"].replace("'", "'\\''")
            
            # 1. Update system clipboard directly using privileged adb shell cmd clipboard (always works)
            subprocess.run([
                "adb", "shell",
                f"cmd clipboard set-text '{escaped_text}'"
            ], capture_output=True)
            
            # 2. Also send broadcast to helper app so it can show Toast and update UI
            res = subprocess.run([
                "adb", "shell",
                f"am broadcast -n '{HELPER_RECEIVER}' -a clipper.set -f 32 -e text '{escaped_text}'"
            ], capture_output=True, text=True)
            if res.returncode == 0:
                print(f"[Sync] Text pushed to Phone: {item['data'][:30]}...")
            else:
                print(f"[Sync Warning] Failed to push clipboard: {res.stderr.strip() or res.stdout.strip()}")
        elif item["type"] == "image":
            remote_path = f"{DROP_ZONE_ANDROID}/clipboard_image.png"
            subprocess.run(["adb", "push", item["data"], remote_path], check=True, capture_output=True)
            print(f"[Sync] Image pushed to Phone: {os.path.basename(item['data'])}")
            send_android_notification("Nothing Sync", "Clipboard image received")
    except Exception as e:
        print(f"[Error] Android Push Failed: {e}")

def sync_clipboard_to_phone(item):
    """Push a Mac clipboard change to the phone. Prefers the live LAN session
    (instant, no ADB); falls back to the ADB path when no session is active."""
    if item["type"] == "text":
        if push_to_phones({"type": "clip", "format": "text", "data": item["data"]}):
            print(f"[Sync] Text pushed to phone over session: {item['data'][:30]}...")
            return
    # No live session (or image payload) — fall back to ADB.
    push_to_android_clipboard(item)

# Native macOS Focus Check
def get_macos_focus_state():
    try:
        res = subprocess.run(
            ["defaults", "read", "com.apple.controlcenter", "NSStatusItem Visible FocusModes"],
            capture_output=True, text=True
        )
        return res.stdout.strip() == "1"
    except:
        return False

def run_adb_connect(address):
    print(f"[ADB] Attempting connection to: {address}")
    res = subprocess.run(["adb", "connect", address], capture_output=True, text=True)
    out = res.stdout.strip()
    print(f"[ADB] Result: {out}")
    if "connected to" in out or "already connected to" in out:
        config = load_config()
        config["last_address"] = address
        save_config(config)
        # Setup reverse port forward for real-time cursor/media commands
        subprocess.run(["adb", "reverse", f"tcp:{ADB_REVERSE_PORT}", f"tcp:{LAN_PORT}"], capture_output=True)
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
    print(f"[ADB] Attempting to pair with: {address} using code {code}")
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
                        subprocess.run(["adb", "shell", f"cmd notification dnd {state_str}"], capture_output=True)
                        print(f"[Focus] Synced Focus Mode '{state_str}' to Android (ADB)")
            except Exception as e:
                print(f"[Focus] Error syncing DND to Android: {e}")
                
        time.sleep(10)

def mac_clipboard_watcher():
    # Watch Mac clipboard for copy events
    global CURRENT_CLIPBOARD_CONTENT
    print("[Watcher] Started macOS Clipboard monitor")
    while True:
        try:
            item, count = get_mac_clipboard()
            if item:
                if item["type"] == "text":
                    with sync_state_lock:
                        if item["data"] != CURRENT_CLIPBOARD_CONTENT:
                            CURRENT_CLIPBOARD_CONTENT = item["data"]
                            db.add_item(CURRENT_CLIPBOARD_CONTENT)
                            threading.Thread(target=sync_clipboard_to_phone, args=(item,)).start()
                else:
                    threading.Thread(target=sync_clipboard_to_phone, args=(item,)).start()
        except Exception as e:
            pass
        time.sleep(0.2)

def android_event_monitor():
    global CURRENT_CLIPBOARD_CONTENT, app_delegate
    
    # Persistent shell script to monitor clipboard, focus, and files on Android
    # Optimized ADB shell script with differentiated polling intervals (L1, L2):
    # - Clipboard: every 3rd iteration (600ms) — low latency for user-facing sync
    # - Files/DND: every 25th iteration (~5s) — less frequent, reduces ADB overhead
    shell_script = """
last_clip=""
last_files=""
last_zen=""
mkdir -p /sdcard/Android/data/com.nothing.airshare/files/ToMac
count=0
while true; do
  count=$((count + 1))
  if [ $((count % 3)) -eq 0 ]; then
    data_only=$(cmd clipboard get-text 2>/dev/null | sed -e 's/\r//g')
    if [ -z "$data_only" ]; then
      curr_clip_raw=$(am broadcast -n "TEMPLATE_HELPER_RECEIVER" -a clipper.get -f 32 2>/dev/null | grep "data=")
      temp="${curr_clip_raw#*data=\\"}"
      data_only="${temp%%\\", extras:*}"
      data_only="${data_only%\\"}"
    fi
    if [ -n "$data_only" ] && [ "$data_only" != "$last_clip" ]; then
      encoded=$(echo -n "$data_only" | base64 | tr -d "\\r\\n")
      echo "CLIPBOARD:$encoded"
      last_clip="$data_only"
    fi
  fi
  if [ $((count % 25)) -eq 0 ]; then
    curr_zen=$(settings get global zen_mode 2>/dev/null)
    if [ "$curr_zen" != "$last_zen" ]; then
      echo "FOCUS:$curr_zen"
      last_zen="$curr_zen"
    fi
    curr_files=$(ls /sdcard/Android/data/com.nothing.airshare/files/ToMac 2>/dev/null)
    if [ "$curr_files" != "$last_files" ]; then
      for file in $curr_files; do
        if ! echo "$last_files" | grep -q "^$file$"; then
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
            device_check = subprocess.run(["adb", "devices"], capture_output=True, text=True)
            lines = device_check.stdout.strip().split('\n')

            if len(lines) < 2 or not lines[1].strip() or "device" not in lines[1]:
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

                if app_delegate and not has_live_session():
                    app_delegate.set_connected(False)
                time.sleep(15)
                continue

            reconnect_attempts = 0
            if app_delegate:
                try:
                    # Setup reverse port forward for real-time cursor/media commands
                    subprocess.run(["adb", "reverse", f"tcp:{ADB_REVERSE_PORT}", f"tcp:{LAN_PORT}"], capture_output=True)
                    print(f"[ADB] Setup reverse port forward tcp:{ADB_REVERSE_PORT} -> tcp:{LAN_PORT}")
                    model_res = subprocess.run(["adb", "shell", "getprop ro.product.model"], capture_output=True, text=True, timeout=3)
                    app_delegate.device_model = model_res.stdout.strip() if (model_res.returncode == 0 and model_res.stdout.strip()) else "Nothing Phone"
                except:
                    app_delegate.device_model = "Nothing Phone"
                app_delegate.set_connected(True)
                
            # Dynamically detect installed helper package
            detect_helper_package()
            
            # Spawn persistent shell script using base64 encoding to prevent quoting issues
            runnable_script = shell_script.replace("TEMPLATE_HELPER_RECEIVER", HELPER_RECEIVER)
            encoded_script = base64.b64encode(runnable_script.encode('utf-8')).decode('utf-8')
            proc = subprocess.Popen(
                ["adb", "shell", f"echo {encoded_script} | base64 -d | sh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )
            
            # Read stdout line-by-line blockingly
            for line in iter(proc.stdout.readline, ""):
                line = line.strip().replace('\r', '')
                if not line:
                    continue
                
                # Handle Clipboard Sync
                if line.startswith("CLIPBOARD:"):
                    encoded_val = line[len("CLIPBOARD:"):]
                    if not encoded_val:
                        continue
                    try:
                        decoded_val = base64.b64decode(encoded_val).decode('utf-8')
                        with sync_state_lock:
                            if decoded_val != CURRENT_CLIPBOARD_CONTENT:
                                print(f"[Android] Clipboard changed: {decoded_val[:20]}...")
                                CURRENT_CLIPBOARD_CONTENT = decoded_val
                                db.add_item(CURRENT_CLIPBOARD_CONTENT)
                                set_mac_clipboard("text", decoded_val)
                                send_mac_notification("Nothing Clipboard", f"Copied: {decoded_val[:30]}")
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
                    threading.Thread(target=pull_file_from_android, args=(filename,)).start()
                else:
                    # Ignore all other output/warnings to keep daemon stable
                    print(f"[ADB Stream Warning] Unexpected line: {line}")
            
            proc.wait()
            print("[ADB Stream] Process exited")
            if app_delegate and not has_live_session():
                app_delegate.set_connected(False)
        except Exception as e:
            print(f"[ADB Stream] Connection broke: {e}")
            if app_delegate and not has_live_session():
                app_delegate.set_connected(False)
        time.sleep(3)

# Helper to create styled template images for status bar
def create_template_dot(filled=True):
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
    return img

def get_current_mac_clipboard_text():
    pb = NSPasteboard.generalPasteboard()
    content = pb.stringForType_(NSStringPboardType)
    return content if content else ""

def push_file_to_android(local_path):
    filename = os.path.basename(local_path)
    remote_path = f"{DROP_ZONE_ANDROID}/{filename}"
    try:
        subprocess.run(["adb", "shell", f"mkdir -p {DROP_ZONE_ANDROID}"], check=True, capture_output=True)
        res = subprocess.run(["adb", "push", local_path, remote_path], check=True, capture_output=True)
        if res.returncode == 0:
            print(f"[Sync] Pushed to Phone: {filename}")
            send_android_notification("Nothing Drop", f"Received: {filename}")
            send_mac_notification("Nothing AirShare", f"Successfully sent {filename} to phone.")
    except Exception as e:
        print(f"[Error] Failed to push {filename}: {e}")
        send_mac_notification("Nothing AirShare Error", f"Failed to push {filename}: {e}")

def trigger_phone_ring():
    print("[Find My Phone] Triggering phone alarm...")
    res = subprocess.run(["adb", "shell", "am", "broadcast", "-a", "clipper.ring"], capture_output=True, text=True)
    if res.returncode == 0:
        print("[Find My Phone] Broadcast sent successfully.")
    else:
        print(f"[Find My Phone] Error sending broadcast: {res.stderr}")

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
        
        version_label = NSTextField.labelWithString_("v2.9.0")
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

    def refresh_data(self):
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
        devices = []
        if bonjour_manager and bonjour_manager.discovered_devices:
            for name in bonjour_manager.discovered_devices:
                devices.append(name)
                
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
        history = db.get_history() if db else []
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
                threading.Thread(target=push_to_android_clipboard, args=({"type": "text", "data": text},), daemon=True).start()

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
            threading.Thread(target=push_to_android_clipboard, args=({"type": "text", "data": clip_text},), daemon=True).start()
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
            print(f"[UI] Restored from history: {text[:20]}...")

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
        threading.Thread(target=self.show_connect_dialog).start()

    def installHelper_(self, sender):
        threading.Thread(target=self.run_install_helper).start()

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
            subprocess.run(["adb", "shell", "settings put global verifier_verify_adb_installs 0"], capture_output=True)
            
            res = subprocess.run(["adb", "install", "-r", local_apk_path], capture_output=True, text=True)
            
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
                threading.Thread(target=run_adb_connect, args=(address,)).start()
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
                threading.Thread(target=self.run_adb_pair_bg, args=(address, code)).start()

    def run_adb_pair_bg(self, address, code):
        print(f"[ADB] Pairing with {address} using code {code}...")
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

def main():
    # Disable ADB's built-in mDNS to prevent duplicate device connections
    os.environ["ADB_MDNS"] = "0"
    try:
        subprocess.run(["adb", "kill-server"], capture_output=True)
        subprocess.run(["adb", "start-server"], capture_output=True)
    except Exception as e:
        print(f"[ADB Init Warning] Failed to restart ADB server: {e}")

    app = NSApplication.sharedApplication()
    # Set as accessory app (menu bar only, no Dock icon, no main window)
    from AppKit import NSApplicationActivationPolicyAccessory
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = ApplicationBootstrap.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    main()
