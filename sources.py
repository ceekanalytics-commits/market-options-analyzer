"""Load and normalize NSE, MarketData.app, and uploaded option chains."""

import io
import os
import zipfile
from datetime import date

import pandas as pd
import requests

from engine import clean_chain


NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": "https://www.nseindia.com/",
}


def _get(url: str, headers: dict | None = None) -> requests.Response:
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        code = getattr(exc.response, "status_code", None)
        if code == 404:
            raise ValueError("No report found for this date. Check that it was an NSE trading day.") from exc
        raise ValueError(f"Download failed: {exc}") from exc


def normalize_nse(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = raw.copy()
    df.columns = df.columns.astype(str).str.strip()
    required = {"TckrSymb", "FinInstrmTp", "XpryDt", "ClsPric", "StrkPric", "OptnTp", "OpnIntrst"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError("NSE bhavcopy is missing: " + ", ".join(sorted(missing)))
    for col in df.select_dtypes(include="object"):
        df[col] = df[col].str.strip()
    kind = df["FinInstrmTp"].replace({
        "OPTIDX": "IDO", "OPTSTK": "SDO", "STO": "SDO",
        "FUTIDX": "IDF", "FUTSTK": "SDF", "STF": "SDF",
    })
    df["XpryDt"] = pd.to_datetime(df["XpryDt"], errors="coerce").dt.date
    df["ClsPric"] = pd.to_numeric(df["ClsPric"], errors="coerce")
    futures = df[kind.isin(("IDF", "SDF")) & df["ClsPric"].gt(0)].copy()
    futures = futures.sort_values("XpryDt")
    reference = {
        (str(row.TckrSymb).upper(), row.XpryDt): float(row.ClsPric)
        for row in futures.itertuples() if pd.notna(row.XpryDt)
    }
    options = df[kind.isin(("IDO", "SDO"))].copy()
    volume_column = next((c for c in ("TtlTradgVol", "TtlTradedVol", "Volume") if c in options), None)
    normalized = pd.DataFrame({
        "symbol": options["TckrSymb"], "expiration": options["XpryDt"],
        "side": options["OptnTp"], "strike": options["StrkPric"],
        "option_price": options["ClsPric"], "open_interest": options["OpnIntrst"],
        "volume": options[volume_column] if volume_column else 0,
    })
    return clean_chain(normalized), reference


def download_nse(trade_date: date) -> tuple[pd.DataFrame, dict]:
    stamp = trade_date.strftime("%Y%m%d")
    filename = f"BhavCopy_NSE_FO_0_0_0_{stamp}_F_0000.csv.zip"
    url = f"https://archives.nseindia.com/content/fo/{filename}"
    try:
        response = _get(url, NSE_HEADERS)
    except ValueError:
        response = _get(url.replace("archives.nseindia.com", "nsearchives.nseindia.com"), NSE_HEADERS)
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            csv_files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_files:
                raise ValueError("NSE archive contains no CSV file.")
            with archive.open(csv_files[0]) as file:
                raw = pd.read_csv(file, low_memory=False)
    except zipfile.BadZipFile as exc:
        raise ValueError("NSE returned an invalid ZIP archive.") from exc
    return normalize_nse(raw)


def download_nse_context(trade_date: date) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    stamp = trade_date.strftime("%d%m%Y")
    reports = []
    for url in (
        f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{stamp}.csv",
        f"https://archives.nseindia.com/content/indices/ind_close_all_{stamp}.csv",
    ):
        try:
            content = _get(url, NSE_HEADERS).content
            frame = pd.read_csv(io.BytesIO(content))
            frame.columns = frame.columns.astype(str).str.strip()
            if len(frame.columns) == 1 or ("Client Type" not in frame and "fao_participant" in url):
                frame = pd.read_csv(io.BytesIO(content), header=1)
                frame.columns = frame.columns.astype(str).str.strip()
            reports.append(frame)
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError):
            reports.append(None)
    return reports[0], reports[1]


def normalize_marketdata(data: dict) -> pd.DataFrame:
    if data.get("s") == "no_data":
        raise ValueError("No option chain was returned for this symbol and date.")
    if data.get("s") != "ok":
        raise ValueError(data.get("errmsg", "MarketData.app returned an unexpected response."))
    symbols = data.get("optionSymbol")
    if not isinstance(symbols, list):
        raise ValueError("MarketData.app response lacks optionSymbol.")
    size = len(symbols)
    columns = {key: value for key, value in data.items() if isinstance(value, list) and len(value) == size}
    raw = pd.DataFrame(columns)
    if raw.empty:
        raise ValueError("No option contracts were returned.")
    expiry = raw.get("expiration")
    if expiry is None:
        raise ValueError("MarketData.app response lacks expiration.")
    if pd.api.types.is_numeric_dtype(expiry):
        expiration = pd.to_datetime(expiry, unit="s", utc=True).dt.tz_convert("America/New_York").dt.date
    else:
        expiration = pd.to_datetime(expiry, errors="coerce").dt.date
    mid = pd.to_numeric(raw.get("mid"), errors="coerce") if "mid" in raw else pd.Series(float("nan"), index=raw.index)
    last = pd.to_numeric(raw.get("last"), errors="coerce") if "last" in raw else pd.Series(float("nan"), index=raw.index)
    option_price = mid.where(mid.gt(0), last)
    normalized = pd.DataFrame({
        "symbol": raw.get("underlying", pd.Series("", index=raw.index)),
        "expiration": expiration, "side": raw.get("side"),
        "strike": raw.get("strike"), "option_price": option_price,
        "volume": raw.get("volume", pd.Series(0, index=raw.index)),
        "open_interest": raw.get("openInterest", pd.Series(0, index=raw.index)),
        "underlying_price": raw.get("underlyingPrice"),
        "bid": raw.get("bid"), "ask": raw.get("ask"),
        "contract": raw.get("optionSymbol"),
    })
    return clean_chain(normalized)


def download_us(symbol: str, trade_date: date, token: str | None = None) -> pd.DataFrame:
    token = token or os.environ.get("MARKETDATA_TOKEN")
    if not token:
        raise ValueError("Enter a MarketData.app API token or set MARKETDATA_TOKEN.")
    url = f"https://api.marketdata.app/v1/options/chain/{symbol.upper().strip()}/"
    try:
        response = requests.get(url, params={"date": trade_date.isoformat()},
                                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                                timeout=60)
    except requests.RequestException as exc:
        raise ValueError(f"MarketData.app request failed: {exc}") from exc
    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise ValueError(f"MarketData.app returned HTTP {response.status_code} without JSON data.") from exc
    if response.status_code not in (200, 203):
        raise ValueError(f"MarketData.app HTTP {response.status_code}: {payload.get('errmsg', 'request failed')}")
    return normalize_marketdata(payload)


def normalize_upload(content: bytes, filename: str) -> tuple[pd.DataFrame, dict]:
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise ValueError("ZIP file contains no CSV.")
            with archive.open(names[0]) as file:
                raw = pd.read_csv(file, low_memory=False)
    else:
        raw = pd.read_csv(io.BytesIO(content), low_memory=False)
    raw.columns = raw.columns.astype(str).str.strip()
    if "FinInstrmTp" in raw:
        return normalize_nse(raw)
    if "optionSymbol" in raw and "side" in raw:
        # CSV exported from the MarketData.app API or the companion fetch script.
        raw["s"] = "ok"
        payload = {column: raw[column].tolist() for column in raw if column != "s"}
        payload["s"] = "ok"
        return normalize_marketdata(payload), {}
    aliases = {
        "type": "side", "option_type": "side", "expiry": "expiration",
        "close": "option_price", "last": "option_price", "price": "option_price",
        "openInterest": "open_interest", "open interest": "open_interest",
        "underlyingPrice": "underlying_price", "underlying": "symbol",
    }
    return clean_chain(raw.rename(columns=aliases)), {}
