#!/usr/bin/env bash
# Start DisplayMonitor at every login: a systemd user service on Linux, a launchd agent on macOS.
# Remove it with scripts/uninstall_autostart.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PYBIN="$ROOT/.venv/bin/python"
[ -x "$PYBIN" ] || { echo "run scripts/setup.sh first" >&2; exit 1; }
mkdir -p logs

case "$(uname -s)" in
  Linux)
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/displaymonitor.service" <<EOF
[Unit]
Description=DisplayMonitor (TURZX 3.5" USB display)
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$PYBIN -m displaymonitor
# SIGTERM makes the program show its "Ciao" screen and exit cleanly
KillSignal=SIGTERM
TimeoutStopSec=8
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF
    # the tray icon needs to know the desktop session
    systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_SESSION_ID 2>/dev/null || true
    systemctl --user daemon-reload
    systemctl --user enable --now displaymonitor.service
    echo "systemd user service installed and started (journalctl --user -u displaymonitor -f)."
    echo "To start it even before you log in:  sudo loginctl enable-linger $USER   (the tray icon needs a desktop session)"
    ;;
  Darwin)
    PLIST="$HOME/Library/LaunchAgents/com.displaymonitor.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.displaymonitor</string>
  <key>ProgramArguments</key><array><string>$PYBIN</string><string>-m</string><string>displaymonitor</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$ROOT/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/launchd.err.log</string>
</dict>
</plist>
EOF
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "launchd agent installed and started ($PLIST)."
    ;;
  *) echo "unsupported system: $(uname -s)" >&2; exit 1 ;;
esac
