#!/bin/bash
# Headache Forecast uninstaller. Double-click (or: bash uninstall.command).
# Removes the nightly check and the menu bar item. Asks before deleting your log.
set -uo pipefail

DEST="${HF_DEST:-$HOME/headache-forecast}"
AGENTS="${HF_AGENTS:-$HOME/Library/LaunchAgents}"
DRY="${HF_DRY_RUN:-0}"
LABEL="com.headache-forecast.nightly"

[ "$DRY" = 1 ] || launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
rm -f "$AGENTS/$LABEL.plist"
echo "Removed the nightly check."

PLUGDIR=""
[ "$DRY" = 1 ] || PLUGDIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
for dir in "$PLUGDIR" "$DEST/swiftbar-plugins"; do
  [ -n "$dir" ] && rm -f "$dir/headache-forecast.30m.sh"
done
[ "$DRY" = 1 ] || open -g "swiftbar://refreshallplugins" 2>/dev/null
echo "Removed the menu bar item."

if [ -d "$DEST" ]; then
  echo
  echo "Your headache log and settings are in: $DEST"
  read -r -p "Delete them too? This can't be undone. [y/N] " ans
  if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
    rm -rf "$DEST"
    echo "Deleted."
  else
    echo "Kept. (log.csv opens in Numbers or Excel.)"
  fi
fi

echo
echo "SwiftBar itself is still installed, in case you use it for other things."
echo "To remove it too, drag /Applications/SwiftBar.app to the Trash."
