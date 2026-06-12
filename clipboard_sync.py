import time
import subprocess
import threading
from AppKit import NSPasteboard, NSStringPboardType

# Configuration
CHECK_INTERVAL = 1.0  # Seconds
CURRENT_CLIPBOARD_CONTENT = ""

def get_mac_clipboard():
    pb = NSPasteboard.generalPasteboard()
    content = pb.stringForType_(NSStringPboardType)
    return content if content else ""

def set_mac_clipboard(text):
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSStringPboardType)

def get_android_clipboard():
    try:
        # Using 'cmd clipboard get-text' as requested in the plan
        result = subprocess.run(
            ["adb", "shell", "cmd clipboard get-text"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[Error] Failed to get Android clipboard: {e}")
        return ""
    except FileNotFoundError:
        print("[Error] ADB not found. Please install platform-tools.")
        return ""

def set_android_clipboard(text):
    try:
        # Escaping single quotes for the shell command
        escaped_text = text.replace("'", "'\\''")
        subprocess.run(
            ["adb", "shell", f"cmd clipboard set-text '{escaped_text}'"],
            check=True
        )
        print(f"[Sync] Pushed to Android: {text[:30]}...")
    except subprocess.CalledProcessError as e:
        print(f"[Error] Failed to set Android clipboard: {e}")

def sync_loop():
    global CURRENT_CLIPBOARD_CONTENT
    
    # Initialize with current Mac clipboard
    CURRENT_CLIPBOARD_CONTENT = get_mac_clipboard()
    print(f"[Status] Clipboard Sync Started. Initial content: {CURRENT_CLIPBOARD_CONTENT[:20]}...")

    while True:
        try:
            # 1. Check Mac Clipboard
            mac_content = get_mac_clipboard()
            if mac_content != CURRENT_CLIPBOARD_CONTENT:
                print(f"[Mac] Change detected: {mac_content[:20]}...")
                CURRENT_CLIPBOARD_CONTENT = mac_content
                set_android_clipboard(mac_content)
            
            # 2. Check Android Clipboard
            android_content = get_android_clipboard()
            if android_content and android_content != CURRENT_CLIPBOARD_CONTENT:
                print(f"[Android] Change detected: {android_content[:20]}...")
                CURRENT_CLIPBOARD_CONTENT = android_content
                set_mac_clipboard(android_content)
                print(f"[Sync] Pushed to Mac: {android_content[:30]}...")
                
        except Exception as e:
            print(f"[Loop Error] {e}")
            
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    # Check if ADB is connected
    try:
        adb_check = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        if "device" not in adb_check.stdout.split('\n')[1]:
            print("[Warning] No ADB device detected. Please connect your Nothing Phone via Wireless Debugging.")
    except FileNotFoundError:
        print("[Error] ADB command not found.")
        
    sync_loop()
