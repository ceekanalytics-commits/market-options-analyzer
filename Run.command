#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! python3 -c 'import streamlit, pandas, numpy, plotly, requests' >/dev/null 2>&1; then
  echo "Installing app dependencies..."
  python3 -m pip install -r requirements.txt
fi
python3 -m streamlit run app.py --server.address localhost
