import time
import subprocess
import os
import shutil
from AppKit import NSPasteboard, NSStringPboardType, NSFilenamesPboardType, NSImagePboardType, NSImage
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configuration
DROP_ZONE_MAC = os.path.expanduser("~/NothingDrop")
DROP_ZONE_ANDROID = "/sdcard/Download/NothingDrop"
CHECK_INTERVAL = 1.0
CURRENT_CLIPBOARD_CONTENT = ""

# Ensure Drop Zone exists
os.makedirs(DROP_ZONE_MAC, exist_ok=True)

class MacDropHandler(FileSystemEventHandler):
    """Monitors the Mac Drop folder and pushes files to Android."""
    def on_created(self, event):
        if not event.is_directory:
            print(f"[Drop] New file on Mac: {os.path.basename(event.src_path)}")
            self.push_to_android(event.src_path)
            
    def push_to_android(self, local_path):
        filename = os.path.basename(local_path)
        remote_path = f"{DROP_ZONE_ANDROID}/{filename}"
        try:
            # Ensure remote directory exists
            subprocess.run(["adb", "shell", f"mkdir -p {DROP_ZONE_ANDROID}"], check=True)
            # Push file
            subprocess.run(["adb", "push", local_path, remote_path], check=True)
            print(f"[Sync] File pushed to Android: {filename}")
        except Exception as e:
            print(f"[Error] Failed to push file: {e}")

def get_mac_clipboard():
    pb = NSPasteboard.generalPasteboard()
    
    # 1. Check for Files
    if pb.availableTypeFromArray_([NSFilenamesPboardType]):
        files = pb.propertyListForType_(NSFilenamesPboardType)
        if files: return f"FILE:{files[0]}"
        
    # 2. Check for Images
    if pb.availableTypeFromArray_([NSImagePboardType]):
        # We handle images by saving them to a temporary file and pushing
        return "IMAGE_DATA"
        
    # 3. Check for Text
    content = pb.stringForType_(NSStringPboardType)
    return content if content else ""

def set_mac_clipboard(text):
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSStringPboardType)

def sync_loop():
    global CURRENT_CLIPBOARD_CONTENT
    print("[Status] Multi-sync Started. Monitoring Clipboard & ~/NothingDrop")
    
    # Start File Watcher
    event_handler = MacDropHandler()
    observer = Observer()
    observer.schedule(event_handler, DROP_ZONE_MAC, recursive=False)
    observer.start()

    while True:
        try:
            # Clipboard Sync Logic (Text Only for now, expansion pending)
            mac_content = get_mac_clipboard()
            
            # Simple Text Sync
            if not mac_content.startswith("FILE:") and mac_content != "IMAGE_DATA":
                if mac_content != CURRENT_CLIPBOARD_CONTENT:
                    CURRENT_CLIPBOARD_CONTENT = mac_content
                    # Push text to Android
                    escaped_text = mac_content.replace("'", "'\\''")
                    subprocess.run(["adb", "shell", f"cmd clipboard set-text '{escaped_text}'"], stderr=subprocess.DEVNULL)
            
            # Android -> Mac Pull (Text)
            res = subprocess.run(["adb", "shell", "cmd clipboard get-text"], capture_output=True, text=True)
            android_text = res.stdout.strip()
            if android_text and android_text != CURRENT_CLIPBOARD_CONTENT:
                CURRENT_CLIPBOARD_CONTENT = android_text
                set_mac_clipboard(android_text)
                
        except Exception as e:
            pass
            
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    sync_loop()
