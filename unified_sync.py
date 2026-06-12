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
    NSSharingService, NSSharingServiceTypeSendViaAirDrop
)
from Foundation import NSObject, NSURL
import objc
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

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

# Ensure directories exist
os.makedirs(DROP_ZONE_MAC, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# Global sync state
CURRENT_CLIPBOARD_CONTENT = ""
LAST_CHANGE_COUNT = -1
app_delegate = None
db = None

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
def get_mac_clipboard():
    pb = NSPasteboard.generalPasteboard()
    change_count = pb.changeCount()
    
    global LAST_CHANGE_COUNT
    if change_count == LAST_CHANGE_COUNT:
        return None, change_count
    
    LAST_CHANGE_COUNT = change_count
    
    # 1. Check for Files
    if pb.availableTypeFromArray_([NSFilenamesPboardType]):
        files = pb.propertyListForType_(NSFilenamesPboardType)
        if files: return {"type": "file", "data": files[0]}, change_count
        
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
            return {"type": "image", "data": temp_path}, change_count
        
    # 3. Check for Text
    content = pb.stringForType_(NSStringPboardType)
    if content:
        return {"type": "text", "data": content}, change_count
        
    return None, change_count

def set_mac_clipboard(type, data):
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    if type == "text":
        pb.setString_forType_(data, NSStringPboardType)
    elif type == "image":
        image = NSImage.alloc().initByReferencingFile_(data)
        if image:
            pb.writeObjects_([image])

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
    subprocess.run(["adb", "connect", address], capture_output=True)

# Threads for operations
def status_polling_loop():
    # Monitors Focus and Battery
    last_dnd_state = None
    while True:
        if app_delegate and app_delegate.connected:
            # 1. Battery Check
            try:
                res = subprocess.run(["adb", "shell", "dumpsys battery"], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    level = None
                    charging = False
                    for line in res.stdout.splitlines():
                        if "level:" in line:
                            level = int(line.split(":")[1].strip())
                        if "status:" in line:
                            status = int(line.split(":")[1].strip())
                            charging = status in (2, 5)
                    if level is not None:
                        app_delegate.update_battery_level_charging(level, charging)
            except Exception as e:
                print(f"[Battery] Error checking battery: {e}")
                
            # 2. DND Sync (Mac -> Android)
            try:
                dnd_state = get_macos_focus_state()
                if dnd_state != last_dnd_state:
                    last_dnd_state = dnd_state
                    state_str = "on" if dnd_state else "off"
                    subprocess.run(["adb", "shell", f"cmd notification dnd {state_str}"], capture_output=True)
                    print(f"[Focus] Synced Focus Mode '{state_str}' to Android")
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
                    if item["data"] != CURRENT_CLIPBOARD_CONTENT:
                        CURRENT_CLIPBOARD_CONTENT = item["data"]
                        db.add_item(CURRENT_CLIPBOARD_CONTENT)
                        threading.Thread(target=push_to_android_clipboard, args=(item,)).start()
                else:
                    threading.Thread(target=push_to_android_clipboard, args=(item,)).start()
        except Exception as e:
            pass
        time.sleep(0.2)

def android_event_monitor():
    # Watches Android clipboard and file drop directory via a single persistent stream
    global CURRENT_CLIPBOARD_CONTENT
    
    shell_script = """
last_clip=""
last_files=""
last_zen=""
mkdir -p /sdcard/Android/data/com.nothing.airshare/files/ToMac
count=0
while true; do
  curr_zen=$(settings get global zen_mode 2>/dev/null)
  if [ "$curr_zen" != "$last_zen" ]; then
    echo "FOCUS:$curr_zen"
    last_zen="$curr_zen"
  fi
  count=$((count + 1))
  if [ $((count % 10)) -eq 0 ]; then
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
  if [ $count -ge 10 ]; then
    count=0
    curr_files=$(ls /sdcard/Android/data/com.nothing.airshare/files/ToMac 2>/dev/null)
    if [ "$curr_files" != "$last_files" ]; then
      for file in $curr_files; do
        if ! echo "$last_files" | grep -q "^$file$"; then
          echo "FILE:$file"
        fi
      done
      last_files="$curr_files"
    fi
  fi
  sleep 0.2
done
"""
    
    while True:
        try:
            # Check if any ADB devices are connected
            device_check = subprocess.run(["adb", "devices"], capture_output=True, text=True)
            lines = device_check.stdout.strip().split('\n')
            
            if len(lines) < 2 or not lines[1].strip() or "device" not in lines[1]:
                # Try auto-connecting to saved address
                config = load_config()
                if "last_address" in config:
                    print(f"[ADB] Trying auto-reconnect to {config['last_address']}...")
                    subprocess.run(["adb", "connect", config["last_address"]], capture_output=True, timeout=5)
                    time.sleep(2)
                    continue
                
                if app_delegate:
                    app_delegate.set_connected(False)
                time.sleep(4)
                continue
            
            if app_delegate:
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
            if app_delegate:
                app_delegate.set_connected(False)
        except Exception as e:
            print(f"[ADB Stream] Connection broke: {e}")
            if app_delegate:
                app_delegate.set_connected(False)
        time.sleep(3)

# App startup logic
class ApplicationBootstrap(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        global app_delegate, db
        
        # Instantiate history database
        db = ClipboardHistoryDB()
        
        # Setup Status Bar
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("⚫️")
        
        app_delegate = self
        self.connected = False
        self.battery_level = "--"
        self.charging = False
        
        # Build default menu UI
        self.updateUIOnMainThread()
        
        # Start background threads
        threading.Thread(target=android_event_monitor, daemon=True).start()
        threading.Thread(target=mac_clipboard_watcher, daemon=True).start()
        threading.Thread(target=status_polling_loop, daemon=True).start()
        
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
        self.battery_level = str(level)
        self.charging = charging
        self.update_menu()

    def update_menu(self):
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "updateUIOnMainThread", None, False
        )

    def updateUIOnMainThread(self):
        if self.connected:
            icon = "⚪️"
            battery_str = f" {self.battery_level}%"
            if self.charging:
                battery_str += " ⚡️"
            self.status_item.button().setTitle_(f"{icon}{battery_str}")
        else:
            self.status_item.button().setTitle_("⚫️")

        menu = NSMenu.alloc().init()

        status_text = f"Nothing Phone: {'Connected' if self.connected else 'Searching...'}"
        status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(status_text, None, "")
        status_item.setEnabled_(False)
        menu.addItem_(status_item)

        if self.connected:
            battery_text = f"Battery: {self.battery_level}% {'(Charging)' if self.charging else ''}"
            battery_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(battery_text, None, "")
            battery_item.setEnabled_(False)
            menu.addItem_(battery_item)

        menu.addItem_(NSMenuItem.separatorItem())

        history_menu = NSMenu.alloc().init()
        self.history = db.get_history()
        if not self.history:
            empty_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("History empty", None, "")
            empty_item.setEnabled_(False)
            history_menu.addItem_(empty_item)
        else:
            for text in self.history:
                display_text = text.replace('\n', ' ')
                display_text = display_text if len(display_text) < 30 else f"{display_text[:27]}..."
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    display_text, "restoreClipboard:", ""
                )
                item.setRepresentedObject_(text)
                history_menu.addItem_(item)

        history_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Clipboard History", None, "")
        history_parent.setSubmenu_(history_menu)
        menu.addItem_(history_parent)

        menu.addItem_(NSMenuItem.separatorItem())

        global LAST_PULLED_FILE
        if LAST_PULLED_FILE and os.path.exists(LAST_PULLED_FILE):
            display_name = os.path.basename(LAST_PULLED_FILE)
            if len(display_name) > 30:
                display_name = display_name[:27] + "..."
            airdrop_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"AirDrop '{display_name}' to iOS...", "airdropLastFile:", ""
            )
            menu.addItem_(airdrop_item)
            menu.addItem_(NSMenuItem.separatorItem())

        open_folder_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open NothingDrop Folder", "openNothingDrop:", ""
        )
        menu.addItem_(open_folder_item)

        connect_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Connect Wireless ADB...", "connectADB:", ""
        )
        menu.addItem_(connect_item)

        if self.connected:
            install_helper_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Install Nothing AirShare APK...", "installHelper:", ""
            )
            menu.addItem_(install_helper_item)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Nothing Sync", "quitApp:", "")
        menu.addItem_(quit_item)

        self.status_item.setMenu_(menu)

    def restoreClipboard_(self, sender):
        text = sender.representedObject()
        if text:
            set_mac_clipboard("text", text)
            print(f"[UI] Restored from history: {text[:20]}...")

    def airdropLastFile_(self, sender):
        global LAST_PULLED_FILE
        if LAST_PULLED_FILE and os.path.exists(LAST_PULLED_FILE):
            url = NSURL.fileURLWithPath_(LAST_PULLED_FILE)
            service = NSSharingService.sharingServiceNamed_(NSSharingServiceTypeSendViaAirDrop)
            if service:
                service.performWithItems_([url])
                print(f"[AirDrop] Shared last pulled file with iOS/AirDrop: {LAST_PULLED_FILE}")

    def openNothingDrop_(self, sender):
        workspace = NSWorkspace.sharedWorkspace()
        workspace.openFile_(DROP_ZONE_MAC)

    def connectADB_(self, sender):
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
        from AppKit import NSAlert, NSTextField
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Connect ADB Wireless")
        alert.setInformativeText_("Enter Nothing Phone's IP and Port (e.g. 192.168.1.100:5555):")
        alert.addButtonWithTitle_("Connect")
        alert.addButtonWithTitle_("Cancel")
        
        input_field = NSTextField.alloc().initWithFrame_(((0, 0), (200, 24)))
        input_field.setPlaceholderString_("192.168.1.100:5555")
        alert.setAccessoryView_(input_field)
        
        response = alert.runModal()
        if response == 1000:
            address = input_field.stringValue()
            if address:
                save_config({"last_address": address})
                threading.Thread(target=run_adb_connect, args=(address,)).start()

    def quitApp_(self, sender):
        NSApplication.sharedApplication().terminate_(None)

def main():
    app = NSApplication.sharedApplication()
    delegate = ApplicationBootstrap.alloc().init()
    app.setDelegate_(delegate)
    app.run()

if __name__ == "__main__":
    main()
