#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating Python environment..."
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

if [[ ! -f "$VENV_DIR/.voiceclean-deps" ]] || [[ "$APP_DIR/requirements.txt" -nt "$VENV_DIR/.voiceclean-deps" ]]; then
  echo "Installing application dependencies..."
  python -m pip install --upgrade pip
  python -m pip install -r "$APP_DIR/requirements.txt"
  touch "$VENV_DIR/.voiceclean-deps"
fi

exec python "$APP_DIR/main.py" "$@"

