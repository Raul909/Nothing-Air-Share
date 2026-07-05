#!/bin/bash
# =============================================================================
#  Nothing AirShare — one-click macOS setup & launcher
#
#  Non-technical users: just DOUBLE-CLICK this file.
#  (First time: right-click it -> Open -> Open, because it's from the internet.)
#
#  It installs everything it needs the first time, then launches the menu-bar
#  app every time after that. Look for the  ⚫️  dot in your menu bar.
# =============================================================================

# Always run from the folder this script lives in.
cd "$(dirname "$0")" || exit 1

echo ""
echo "  ⚫️  Nothing AirShare — setting up your Mac..."
echo "  ---------------------------------------------"
echo ""

# --- 1. Homebrew (the installer for the pieces we need) ----------------------
if ! command -v brew >/dev/null 2>&1; then
  echo "→ Installing Homebrew. macOS may ask for your Mac password."
  echo "  (When typing your password, nothing shows on screen — that's normal.)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Make sure brew is on PATH for this session (Apple Silicon + Intel locations).
[ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
[ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"

if ! command -v brew >/dev/null 2>&1; then
  echo "❌ Homebrew isn't available. Please restart your Mac and run this again."
  echo "   Press Return to close."; read -r _; exit 1
fi

# --- 2. adb (talks to your phone) + python -----------------------------------
if ! command -v adb >/dev/null 2>&1; then
  echo "→ Installing Android platform tools (adb)..."
  brew install android-platform-tools
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "→ Installing Python..."
  brew install python
fi

# --- 3. Python environment + dependencies (only downloads once) --------------
if [ ! -d .venv ]; then
  echo "→ Creating Python environment..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python3 -c "import objc, watchdog, PIL, PyInstaller" >/dev/null 2>&1; then
  echo "→ Installing app dependencies (one-time, ~1 min)..."
  python3 -m pip install --quiet --upgrade pip
  python3 -m pip install --quiet \
    pyobjc-framework-Cocoa pyobjc-framework-Quartz \
    pyobjc-framework-Accessibility pyobjc-framework-ApplicationServices \
    watchdog Pillow pyinstaller
fi

# --- 4. Build and Install App ------------------------------------------------
echo "→ Building standalone macOS App..."
pyinstaller --noconsole --name "Nothing AirShare" unified_sync.py >/dev/null 2>&1
plutil -insert LSUIElement -bool YES "dist/Nothing AirShare.app/Contents/Info.plist" >/dev/null 2>&1

echo "→ Installing to /Applications..."
rm -rf "/Applications/Nothing AirShare.app"
cp -R "dist/Nothing AirShare.app" "/Applications/"
rm -rf build dist "Nothing AirShare.spec"

# --- 5. Launch ---------------------------------------------------------------
echo ""
echo "  ✅ Ready! Launching Nothing AirShare."
echo "  Look for the  ⚫️  dot in your menu bar (top-right of the screen)."
echo "  You can now launch 'Nothing AirShare' directly from your Applications folder!"
echo ""
open "/Applications/Nothing AirShare.app"
