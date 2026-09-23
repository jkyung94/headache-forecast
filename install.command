#!/bin/bash
# Headache Forecast installer. Double-click (or: bash install.command).
# Safe to run again: it upgrades the code and keeps your log and settings.
#
# Test hooks (used to check the installer without touching the real system):
#   HF_DEST=/path     install location (default ~/headache-forecast)
#   HF_AGENTS=/path   LaunchAgents folder (default ~/Library/LaunchAgents)
#   HF_DRY_RUN=1      skip launchctl, SwiftBar install/settings, and opening apps
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${HF_DEST:-$HOME/headache-forecast}"
AGENTS="${HF_AGENTS:-$HOME/Library/LaunchAgents}"
DRY="${HF_DRY_RUN:-0}"
LABEL="com.headache-forecast.nightly"
PLIST="$AGENTS/$LABEL.plist"

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }

say "Headache Forecast: installing"

# ---- 1. Python 3.8+ (standard library only, nothing to pip install)
ok_python() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; }
PY=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if [ -x "$p" ] && ok_python "$p"; then PY="$p"; break; fi
done
# /usr/bin/python3 is only a stub until Apple's Command Line Tools are installed;
# calling it without them pops an install dialog, so check first.
if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && ok_python /usr/bin/python3; then
  PY=/usr/bin/python3
fi
if [ -z "$PY" ]; then
  say "Python 3 is needed first."
  echo "A window from Apple will ask to install the Command Line Tools (free, ~5-10 min)."
  echo "When it finishes, run this installer again."
  [ "$DRY" = 1 ] || xcode-select --install >/dev/null 2>&1 || true
  exit 1
fi
echo "Python: $PY"

# ---- 2. SwiftBar (shows the forecast in the menu bar)
if [ "$DRY" != 1 ] && [ ! -d /Applications/SwiftBar.app ] && [ ! -d "$HOME/Applications/SwiftBar.app" ]; then
  if command -v brew >/dev/null 2>&1; then
    say "Installing SwiftBar with Homebrew..."
    brew install --cask swiftbar
  else
    say "SwiftBar is needed for the menu bar."
    echo "Opening swiftbar.app: download it and drag it into Applications."
    open "https://swiftbar.app"
    read -r -p "Press Return once SwiftBar is in Applications... " _
    if [ ! -d /Applications/SwiftBar.app ]; then
      echo "Still can't find /Applications/SwiftBar.app. Run this installer again once it's there."
      exit 1
    fi
  fi
fi

# ---- 3. Files (keeps config.json, log.csv, history.csv from an earlier install)
mkdir -p "$DEST"
cp "$SRC"/predict.py "$SRC"/report.py "$SRC"/backtest_thresholds.py \
   "$SRC"/log_dialog.applescript "$SRC"/README.md "$DEST"/
echo "Installed to: $DEST"

# ---- 4. Menu bar plugin. Reuse SwiftBar's plugin folder if it already has one.
PLUGDIR=""
if [ "$DRY" != 1 ]; then
  PLUGDIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
fi
if [ -z "$PLUGDIR" ] || [ ! -d "$PLUGDIR" ]; then
  PLUGDIR="$DEST/swiftbar-plugins"
  [ "$DRY" = 1 ] || defaults write com.ameba.SwiftBar PluginDirectory "$PLUGDIR"
fi
mkdir -p "$PLUGDIR"
cat > "$PLUGDIR/headache-forecast.30m.sh" <<EOF
#!/bin/bash
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
exec "$PY" "$DEST/predict.py" --swiftbar
EOF
chmod +x "$PLUGDIR/headache-forecast.30m.sh"
echo "Menu bar plugin: $PLUGDIR/headache-forecast.30m.sh"

# ---- 5. Nightly 9pm check (notifies only on moderate/high nights)
mkdir -p "$AGENTS"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DEST/predict.py</string>
    <string>--quiet</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$DEST/nightly.log</string>
  <key>StandardErrorPath</key><string>$DEST/nightly.log</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null
if [ "$DRY" != 1 ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
fi
echo "Nightly check: 9pm ($PLIST)"

# ---- 6. Location and preventive (first install only; change later from the menu)
if [ ! -f "$DEST/config.json" ]; then
  say "Setup"
  "$PY" "$DEST/predict.py" --setup
fi

# ---- 7. Start the menu bar
if [ "$DRY" != 1 ]; then
  open -a SwiftBar
  sleep 2
  open -g "swiftbar://refreshallplugins" || true
fi

say "Done!"
cat <<'EOF'
- Look for a colored dot (🟢 Low) in the menu bar. If you don't see it, it may be hidden
  behind the notch: hold ⌘ and drag other icons off the menu bar to make room.
- In SwiftBar's menu → Preferences, turn on "Launch at login".
- The first alert may ask to allow notifications from "Script Editor". Allow it.
- Log headaches from the menu (📝). Days you don't log count as headache-free.
EOF
