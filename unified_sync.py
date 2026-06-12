import time
import subprocess
import os
import shutil
import threading
import queue
from AppKit import NSPasteboard, NSStringPboardType, NSFilenamesPboardType, NSImagePboardType, NSImage, NSBitmapImageRep, NSPNGFileType
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configuration
DROP_ZONE_MAC = os.path.expanduser("~/NothingDrop")
DROP_ZONE_ANDROID = "/sdcard/Download/NothingDrop"
TEMP_DIR = os.path.expanduser("~/.nothing_sync_temp")
CHECK_INTERVAL = 0.5 # Faster responsiveness
CURRENT_CLIPBOARD_CONTENT = ""
LAST_CHANGE_COUNT = -1

# Ensure directories exist
os.makedirs(DROP_ZONE_MAC, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

class MacDropHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            print(f"[Drop] New file detected: {os.path.basename(event.src_path)}")
            threading.Thread(target=self.push_to_android, args=(event.src_path,)).start()
            
    def push_to_android(self, local_path):
        filename = os.path.basename(local_path)
        remote_path = f"{DROP_ZONE_ANDROID}/{filename}"
        try:
            subprocess.run(["adb", "shell", f"mkdir -p {DROP_ZONE_ANDROID}"], check=True, capture_output=True)
            subprocess.run(["adb", "push", local_path, remote_path], check=True, capture_output=True)
            print(f"[Sync] Pushed to Phone: {filename}")
        except Exception as e:
            print(f"[Error] Failed to push {filename}: {e}")

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
    if pb.availableTypeFromArray_([NSImagePboardType]):
        image_data = pb.dataForType_(NSPNGFileType)
        if not image_data:
            # Try to convert NSImage to PNG
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

def push_to_android_clipboard(item):
    try:
        if item["type"] == "text":
            escaped_text = item["data"].replace("'", "'\\''")
            subprocess.run(["adb", "shell", f"cmd clipboard set-text '{escaped_text}'"], check=True, capture_output=True)
            print(f"[Sync] Text pushed to Phone: {item['data'][:30]}...")
        elif item["type"] == "image":
            # Android clipboard doesn't easily support raw images via shell, 
            # so we push the file to a known location for Gboard to pick up if it monitors folders,
            # OR we just push it to NothingDrop for easy access.
            remote_path = f"{DROP_ZONE_ANDROID}/clipboard_image.png"
            subprocess.run(["adb", "push", item["data"], remote_path], check=True, capture_output=True)
            print(f"[Sync] Image pushed to Phone: {os.path.basename(item['data'])}")
    except Exception as e:
        print(f"[Error] Android Push Failed: {e}")

def pull_from_android_clipboard():
    try:
        res = subprocess.run(["adb", "shell", "cmd clipboard get-text"], capture_output=True, text=True, timeout=2)
        return res.stdout.strip()
    except:
        return None

def sync_loop():
    global CURRENT_CLIPBOARD_CONTENT
    print("🚀 Nothing Pro-Sync Active [Event-Driven]")
    
    # Start File Watcher
    observer = Observer()
    observer.schedule(MacDropHandler(), DROP_ZONE_MAC, recursive=False)
    observer.start()

    while True:
        try:
            # 1. Mac -> Android (Event Driven via changeCount)
            item, count = get_mac_clipboard()
            if item:
                if item["type"] == "text":
                    if item["data"] != CURRENT_CLIPBOARD_CONTENT:
                        CURRENT_CLIPBOARD_CONTENT = item["data"]
                        threading.Thread(target=push_to_android_clipboard, args=(item,)).start()
                else:
                    # Files/Images are always pushed on change
                    threading.Thread(target=push_to_android_clipboard, args=(item,)).start()
            
            # 2. Android -> Mac (Poll - but we keep it light)
            # Optimization: only check if Mac clipboard hasn't changed in this tick
            android_text = pull_from_android_clipboard()
            if android_text and android_text != CURRENT_CLIPBOARD_CONTENT:
                print(f"[Android] New text: {android_text[:20]}...")
                CURRENT_CLIPBOARD_CONTENT = android_text
                set_mac_clipboard("text", android_text)
                
        except Exception as e:
            # print(f"[Loop Error] {e}")
            pass
            
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    sync_loop()
