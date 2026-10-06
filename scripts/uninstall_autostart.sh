#!/usr/bin/env bash
# Remove the login autostart created by scripts/install_autostart.sh.
set -euo pipefail
case "$(uname -s)" in
  Linux)
    systemctl --user disable --now displaymonitor.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/displaymonitor.service"
    systemctl --user daemon-reload
    echo "systemd user service removed."
    ;;
  Darwin)
    PLIST="$HOME/Library/LaunchAgents/com.displaymonitor.plist"
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "launchd agent removed."
    ;;
  *) echo "unsupported system: $(uname -s)" >&2; exit 1 ;;
esac
