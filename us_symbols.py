"""Searchable directory of US-listed stocks and ETFs."""

import csv
from io import StringIO
import re

import requests
import streamlit as st


DIRECTORIES = (
    ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "Symbol"),
    ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "ACT Symbol"),
)
FALLBACK = {
    "AAPL": "Apple Inc.", "AMZN": "Amazon.com, Inc.", "AMD": "Advanced Micro Devices, Inc.",
    "GOOGL": "Alphabet Inc.", "IWM": "iShares Russell 2000 ETF", "META": "Meta Platforms, Inc.",
    "MSFT": "Microsoft Corporation", "NVDA": "NVIDIA Corporation", "QQQ": "Invesco QQQ Trust",
    "SPY": "SPDR S&P 500 ETF Trust", "TSLA": "Tesla, Inc.",
}
EXCLUDED_NAME_PATTERN = re.compile(r"\b(?:warrants?|rights?|units?|preferred|notes?)\b", re.IGNORECASE)


def parse_directory(contents: str, symbol_column: str) -> dict[str, str]:
    symbols = {}
    for row in csv.DictReader(StringIO(contents), delimiter="|"):
        symbol = (row.get(symbol_column) or "").strip().upper()
        name = (row.get("Security Name") or "").strip()
        if not symbol or not name or (row.get("Test Issue") or "").strip() != "N":
            continue
        if EXCLUDED_NAME_PATTERN.search(name):
            continue
        if not all(char.isalnum() or char in ".-" for char in symbol):
            continue
        symbols[symbol] = name
    return symbols


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def us_stock_options() -> list[str]:
    """Refresh the public exchange listings daily; allow common tickers if offline."""
    symbols = FALLBACK.copy()
    for url, column in DIRECTORIES:
        try:
            response = requests.get(url, timeout=12)
            response.raise_for_status()
            symbols.update(parse_directory(response.text, column))
        except requests.RequestException:
            continue
    return [f"{symbol} — {name}" for symbol, name in sorted(symbols.items())]
