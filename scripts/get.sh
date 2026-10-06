#!/usr/bin/env bash
# Installer for Linux / macOS people WITHOUT git: downloads DisplayMonitor, offers to install Python if it is missing,
# and runs the normal setup (scripts/setup.sh).
#
#   curl -fsSL https://raw.githubusercontent.com/DanaVivaldi/turzx-displaymonitor/main/scripts/get.sh | bash
#   curl -fsSL .../get.sh | bash -s -- --lang it --autostart --dir ~/displaymonitor
#
# Options: --dir <folder> (default ~/DisplayMonitor; an existing install is UPDATED, config/ and assets/ are kept)
#          --lang en|it   --ref <branch|tag> (default main)   --autostart   --no-setup   --no-prompt (never ask)
set -euo pipefail
REPO="DanaVivaldi/turzx-displaymonitor"
DIR="$HOME/DisplayMonitor"; LANG_PACK=""; REF="main"; AUTOSTART=0; SETUP=1; PROMPT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --lang) LANG_PACK="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --autostart) AUTOSTART=1; shift ;;
    --no-setup) SETUP=0; shift ;;
    --no-prompt) PROMPT=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

fetch() { if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"; elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"; else echo "curl or wget is needed" >&2; exit 1; fi; }
command -v tar >/dev/null 2>&1 || { echo "tar is needed" >&2; exit 1; }

# ---- 1. download and unpack ---------------------------------------------------------------------
echo "Downloading DisplayMonitor ($REF) ..."
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
KIND=heads; [[ "$REF" =~ ^v?[0-9]+(\.[0-9]+)*$ ]] && KIND=tags
fetch "https://github.com/$REPO/archive/refs/$KIND/$REF.tar.gz" "$TMP/src.tar.gz"
mkdir -p "$TMP/x" && tar -xzf "$TMP/src.tar.gz" -C "$TMP/x"
SRC="$(find "$TMP/x" -mindepth 1 -maxdepth 1 -type d | head -n1)"
mkdir -p "$DIR"
# program files are replaced; config/*.yaml that are not examples, assets/, logs/ and .venv are never touched
( cd "$SRC" && find . -mindepth 1 -maxdepth 1 ! -name assets ! -name logs ! -name .venv ! -name config -exec cp -R {} "$DIR"/ \; )
mkdir -p "$DIR/config" "$DIR/assets"
cp -R "$SRC"/config/*.example.yaml "$DIR/config/"
[ -d "$SRC/config/themes" ] && cp -R "$SRC/config/themes" "$DIR/config/" || true
echo "Installed in $DIR"
[ "$SETUP" = 1 ] || exit 0

# ---- 2. Python ----------------------------------------------------------------------------------
have_python() { for c in python3.13 python3.12 python3.11 python3.10 python3; do command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)' 2>/dev/null && return 0; done; return 1; }
if ! have_python; then
  echo "Python 3.10-3.13 not found."
  ans=""; [ "$PROMPT" = 1 ] && { read -r -p "Install it with your package manager now (may ask for your password)? [y/N] " ans < /dev/tty || ans=""; }
  if [[ "$ans" =~ ^[yY] ]]; then
    if   command -v brew    >/dev/null 2>&1; then brew install python@3.12
    elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf     >/dev/null 2>&1; then sudo dnf install -y python3 python3-pip
    elif command -v pacman  >/dev/null 2>&1; then sudo pacman -S --noconfirm python python-pip
    elif command -v zypper  >/dev/null 2>&1; then sudo zypper install -y python3 python3-pip
    else echo "No known package manager: install Python 3.12 from https://www.python.org/downloads/ and run this again." >&2; exit 1; fi
  else
    echo "Install Python 3.12 and run this again." >&2; exit 1
  fi
fi

# ---- 3. the normal setup ------------------------------------------------------------------------
cd "$DIR"
SETUP_ARGS=(); [ -n "$LANG_PACK" ] && SETUP_ARGS+=(--lang "$LANG_PACK"); [ "$PROMPT" = 0 ] && SETUP_ARGS+=(--no-prompt)
bash scripts/setup.sh ${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}   # (empty-array safe on macOS bash 3.2)
[ "$AUTOSTART" = 1 ] && bash scripts/install_autostart.sh
echo
echo "Start it:  cd '$DIR' && .venv/bin/python -m displaymonitor"
