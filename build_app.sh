#!/bin/bash
# ============================================================
#  Build "Cloud Backup.app" — macOS application bundle
#  Run this script to create the .app from source files.
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Cloud Backup"
APP_DIR="$SCRIPT_DIR/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"

echo "🔨 Building $APP_NAME.app ..."

# Clean previous build
rm -rf "$APP_DIR"

# Create bundle structure
mkdir -p "$CONTENTS/MacOS"
mkdir -p "$CONTENTS/Resources"

# ── Info.plist ──────────────────────────────────────────────
cat > "$CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Cloud Backup</string>
    <key>CFBundleDisplayName</key>
    <string>Cloud Backup Tool</string>
    <key>CFBundleIdentifier</key>
    <string>com.cloud-backup.tool</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# ── Launcher script ────────────────────────────────────────
cat > "$CONTENTS/MacOS/launcher" << 'LAUNCHER'
#!/bin/bash
RESOURCES_DIR="$(dirname "$0")/../Resources"
SCRIPT="$RESOURCES_DIR/backup.py"
if ! command -v python3 &>/dev/null; then
    if command -v brew &>/dev/null; then
        osascript -e 'tell application "Terminal" to activate' -e "tell application \"Terminal\" to do script \"echo '📦 Installing Python 3...' && brew install python3 && echo '✅ Done! Open Cloud Backup again.' && read -p 'Press Enter...'\""
    else
        osascript -e 'tell application "Terminal" to activate' -e "tell application \"Terminal\" to do script \"echo '📦 Installing Homebrew + Python 3...' && /bin/bash -c \\\"\\\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\\\" && eval \\\"\\\$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)\\\" && brew install python3 && echo '✅ Done! Open Cloud Backup again.' && read -p 'Press Enter...'\""
    fi
    exit 0
fi
osascript -e 'tell application "Terminal" to activate' \
          -e "tell application \"Terminal\" to do script \"python3 '${SCRIPT}' ; echo '' ; echo 'Done! You can close this window.' ; echo '' ; read -p 'Press Enter to close...'\""
LAUNCHER
chmod +x "$CONTENTS/MacOS/launcher"

# ── Copy backup script ─────────────────────────────────────
cp "$SCRIPT_DIR/backup.py" "$CONTENTS/Resources/backup.py"

# ── Generate icon ──────────────────────────────────────────
if [ -f "$SCRIPT_DIR/icon.png" ]; then
    echo "🎨 Building icon from icon.png ..."
    ICONSET=$(mktemp -d)/AppIcon.iconset
    mkdir -p "$ICONSET"

    for sz in 16 32 64 128 256 512 1024; do
        sips -s format png -z $sz $sz "$SCRIPT_DIR/icon.png" --out "$ICONSET/tmp_${sz}.png" 2>/dev/null
    done

    cp "$ICONSET/tmp_16.png"   "$ICONSET/icon_16x16.png"
    cp "$ICONSET/tmp_32.png"   "$ICONSET/icon_16x16@2x.png"
    cp "$ICONSET/tmp_32.png"   "$ICONSET/icon_32x32.png"
    cp "$ICONSET/tmp_64.png"   "$ICONSET/icon_32x32@2x.png"
    cp "$ICONSET/tmp_128.png"  "$ICONSET/icon_128x128.png"
    cp "$ICONSET/tmp_256.png"  "$ICONSET/icon_128x128@2x.png"
    cp "$ICONSET/tmp_256.png"  "$ICONSET/icon_256x256.png"
    cp "$ICONSET/tmp_512.png"  "$ICONSET/icon_256x256@2x.png"
    cp "$ICONSET/tmp_512.png"  "$ICONSET/icon_512x512.png"
    cp "$ICONSET/tmp_1024.png" "$ICONSET/icon_512x512@2x.png"
    rm "$ICONSET"/tmp_*.png

    iconutil -c icns "$ICONSET" -o "$CONTENTS/Resources/AppIcon.icns" 2>/dev/null && \
        echo "   ✅ Icon created" || \
        echo "   ⚠️  Icon creation failed (app will use default icon)"

    rm -rf "$(dirname "$ICONSET")"
else
    echo "ℹ️  No icon.png found — app will use the default macOS icon."
    echo "   Place an icon.png (1024x1024) in this folder and rebuild."
fi

# ── Done ────────────────────────────────────────────────────
touch "$APP_DIR"
echo ""
echo "✅ Built successfully: $APP_NAME.app"
echo ""
echo "Next steps:"
echo "  1. Copy config.example.yaml → config.yaml"
echo "  2. Edit config.yaml with your credentials"
echo "  3. Double-click $APP_NAME.app"
echo ""
