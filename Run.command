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
if ! .venv/bin/python -c 'import streamlit, pandas, numpy, plotly, requests' >/dev/null 2>&1; then
  echo "Installing app dependencies (first launch may take a few minutes)..."
  .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python -m streamlit run app.py --server.address localhost
