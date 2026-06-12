#!/bin/bash
# Exit immediately if a command exits with a non-zero status
set -e

echo "============================================="
echo "   NOTHING AIRSHARE ANDROID APK BUILDER      "
echo "============================================="

# Ensure Homebrew bin directory is in PATH for this execution
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# 1. Check for brew
if ! command -v brew &> /dev/null; then
    echo "Error: Homebrew is required but not found in PATH."
    exit 1
fi

# 2. Check and install OpenJDK 17 & Gradle
if [ ! -d "/opt/homebrew/opt/openjdk@17" ]; then
    echo "[Build Tools] OpenJDK 17 not found. Installing via Homebrew..."
    brew install openjdk@17
else
    echo "[Build Tools] OpenJDK 17 is already installed."
fi

if ! command -v gradle &> /dev/null; then
    echo "[Build Tools] Gradle not found. Installing via Homebrew..."
    brew install gradle
else
    echo "[Build Tools] Gradle is already installed."
fi

# 3. Check and install Android command-line tools
if [ ! -d "/opt/homebrew/share/android-commandlinetools" ]; then
    echo "[Build Tools] Android SDK Command-line Tools not found. Installing..."
    brew install --cask android-commandlinetools
else
    echo "[Build Tools] Android SDK Command-line Tools are already installed."
fi

# 4. Set Environment Variables
export JAVA_HOME="/opt/homebrew/opt/openjdk@17"
export ANDROID_HOME="/opt/homebrew/share/android-commandlinetools"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

echo "JAVA_HOME is set to: $JAVA_HOME"
echo "ANDROID_HOME is set to: $ANDROID_HOME"

# 5. Install required Android SDK platforms and build-tools
echo "[Android SDK] Accepting licenses and installing platform-tools, platform 34, build-tools 34.0.0..."
# Accept licenses automatically
yes | sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-34" "build-tools;34.0.0"

# 6. Build Android APK
echo "[Gradle Build] Building Nothing AirShare Android app..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Generate gradle wrapper 8.4 in a temp directory to avoid plugin evaluation issues with Gradle 9.x
echo "[Gradle] Creating temp wrapper generation directory..."
TEMP_WRAPPER_DIR=$(mktemp -d)
(
    cd "$TEMP_WRAPPER_DIR"
    touch settings.gradle
    gradle wrapper --gradle-version 8.4
)

echo "[Gradle] Copying Gradle 8.4 wrapper to project..."
cp "$TEMP_WRAPPER_DIR/gradlew" "$SCRIPT_DIR/"
cp "$TEMP_WRAPPER_DIR/gradlew.bat" "$SCRIPT_DIR/"
mkdir -p "$SCRIPT_DIR/gradle/wrapper"
cp -R "$TEMP_WRAPPER_DIR/gradle/wrapper/" "$SCRIPT_DIR/gradle/wrapper/"
rm -rf "$TEMP_WRAPPER_DIR"

cd "$SCRIPT_DIR"
# Make gradlew executable
chmod +x gradlew

# Run gradle build
./gradlew assembleDebug

# 7. Copy output debug APK to target directory
OUTPUT_APK="app/build/outputs/apk/debug/app-debug.apk"
DEST_DIR="$HOME/.nothing_sync"
DEST_APK="$DEST_DIR/NothingAirShare.apk"

if [ -f "$OUTPUT_APK" ]; then
    mkdir -p "$DEST_DIR"
    cp "$OUTPUT_APK" "$DEST_APK"
    echo "============================================="
    echo " SUCCESS: APK built successfully!"
    echo " Saved to: $DEST_APK"
    echo "============================================="
else
    echo "Error: Gradle build finished but output APK not found at $OUTPUT_APK"
    exit 1
fi
