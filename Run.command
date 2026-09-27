#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/ and launch again."
  read -r -p "Press Return to close..." _
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating a private Python environment..."
  python3 -m venv .venv
fi
requirements_hash="$(shasum -a 256 requirements.txt | awk '{print $1}')"
installed_hash="$(cat .venv/.requirements-sha256 2>/dev/null || true)"
if [ "$requirements_hash" != "$installed_hash" ]; then
  echo "Installing or updating app dependencies (this may take a few minutes)..."
  .venv/bin/python -m pip install -r requirements.txt
  printf '%s' "$requirements_hash" > .venv/.requirements-sha256
fi
.venv/bin/python -m streamlit run app.py --server.address localhost
