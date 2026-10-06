#!/usr/bin/env bash
# One-time setup for DisplayMonitor on Linux and macOS (the Windows equivalent is scripts/setup.ps1).
#   1. creates the Python virtual environment (.venv) and installs requirements.txt
#   2. Linux: offers to install a udev rule so the display can be used without root
#   3. installs a language pack (English or Italiano) as config/config.yaml + config/pages.yaml if you have none
#
# Usage:  bash scripts/setup.sh [--lang en|it] [--no-prompt]   (--no-prompt: never ask, take the defaults)
# Needs:  Python 3.10 - 3.13 (python3), internet access.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LANG_PACK=""
PROMPT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) LANG_PACK="${2:-}"; shift 2 ;;
    --no-prompt) PROMPT=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

ask() {  # ask "prompt" -> $REPLY (works when the script itself is piped into bash: reads the terminal)
  REPLY=""
  if [ "$PROMPT" = 0 ]; then return 0
  elif [ -t 0 ]; then read -r -p "$1" REPLY || REPLY=""
  elif [ -r /dev/tty ]; then read -r -p "$1" REPLY < /dev/tty || REPLY=""
  fi
}

# ---- 1. Python environment --------------------------------------------------------------------
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10-3.13 not found." >&2
  case "$(uname -s)" in
    Darwin) echo "Install it with:  brew install python@3.12   (or from https://www.python.org/downloads/)" >&2 ;;
    *)      echo "Install it with your package manager, e.g.:  sudo apt install python3 python3-venv python3-pip" >&2 ;;
  esac
  exit 1
fi
echo "Using $($PY --version)"
if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
  echo "The venv module is missing: on Debian / Ubuntu run  sudo apt install python3-venv python3-pip" >&2
  exit 1
fi
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt

# ---- 2. Linux: access to the display without root ---------------------------------------------
if [ "$(uname -s)" = "Linux" ]; then
  RULE=/etc/udev/rules.d/99-turzx.rules
  if [ ! -f "$RULE" ]; then
    ask "Install a udev rule so your user can open the display (needs sudo)? [y/N] "
    if [[ "$REPLY" =~ ^[yY] ]]; then
      sudo cp scripts/linux/99-turzx.rules "$RULE" && sudo udevadm control --reload-rules && sudo udevadm trigger
      echo "udev rule installed: unplug and replug the display."
    else
      echo "Skipped. Without it add yourself to the 'dialout' group (sudo usermod -aG dialout \$USER, then log in again)."
    fi
  else
    echo "udev rule already installed."
  fi
fi

# ---- 3. configuration: language pack ----------------------------------------------------------
if [ ! -f config/config.yaml ] && [ ! -f config/pages.yaml ]; then
  if [ -z "$LANG_PACK" ]; then
    ask "Language pack - en (English) or it (Italiano) [en]: "
    case "$REPLY" in [iI]*) LANG_PACK=it ;; *) LANG_PACK=en ;; esac
  fi
  .venv/bin/python -m displaymonitor --init "$LANG_PACK"
else
  echo "config/config.yaml / pages.yaml already exist: left untouched (change language with:  .venv/bin/python -m displaymonitor --init it --force)"
fi

echo
echo "Done. Try it:           $ROOT/.venv/bin/python -m displaymonitor"
echo "Autostart at login:     bash scripts/install_autostart.sh"
echo "What works where:       docs/PLATFORMS.md"
