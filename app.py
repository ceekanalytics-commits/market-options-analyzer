"""Local Streamlit app for end-of-day option-chain analysis."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import Settings, analyze
from sources import download_nse, download_nse_context, download_us, normalize_upload
from us_symbols import us_stock_options


st.set_page_config(page_title="Market Options Analyzer", page_icon="📊", layout="wide")
st.title("Market Options Analyzer")
st.caption("End-of-day option-chain analysis for NSE and US underlyings, with CSV import for other markets.")


def previous_weekday(before: date) -> date:
    day = before - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def safe_default_date(source: str) -> date:
    if not source.startswith("US"):
        return previous_weekday(date.today())
    now_et = datetime.now(ZoneInfo("America/New_York"))
    release_day = now_et.date()
    if release_day.weekday() >= 5 or now_et.time() < time(9, 30):
        release_day = previous_weekday(release_day)
    return previous_weekday(release_day)


def fmt(value: float | None, decimals: int = 2) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:,.{decimals}f}"


def future_reference(references: dict, symbol: str, expiry: date) -> float | None:
    exact = references.get((symbol, expiry))
    if exact:
        return exact
    candidates = [(ex, price) for (sym, ex), price in references.items() if sym == symbol and ex >= expiry]
    if not candidates:
        candidates = [(ex, price) for (sym, ex), price in references.items() if sym == symbol]
    return min(candidates, key=lambda pair: abs((pair[0] - expiry).days))[1] if candidates else None


def show_smart_money(frame: pd.DataFrame | None) -> None:
    if frame is None or frame.empty:
        st.info("NSE participant open-interest report was unavailable for this date.")
        return
    data = frame.copy()
    data.columns = data.columns.astype(str).str.strip()
    client_col = next((col for col in ("Client Type", "ClientType", "Participant") if col in data), None)
    if not client_col:
        st.dataframe(data, width="stretch")
        return
    data[client_col] = data[client_col].astype(str).str.strip().str.upper()
    categories = {
        "Index futures": ("Future Index Long", "Future Index Short"),
        "Index calls": ("Option Index Call Long", "Option Index Call Short"),
        "Index puts": ("Option Index Put Long", "Option Index Put Short"),
        "Stock futures": ("Future Stock Long", "Future Stock Short"),
    }
    rows = []
    for category, (long_col, short_col) in categories.items():
        if long_col not in data or short_col not in data:
            continue
        for participant in ("FII", "CLIENT"):
            matched = data[data[client_col] == participant]
            if not matched.empty:
                longs = pd.to_numeric(matched[long_col].astype(str).str.replace(",", ""), errors="coerce").sum()
                shorts = pd.to_numeric(matched[short_col].astype(str).str.replace(",", ""), errors="coerce").sum()
                rows.append({"Category": category, "Participant": participant,
                             "Long": longs, "Short": shorts, "Net": longs - shorts})
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.dataframe(data, width="stretch")


def show_sectors(frame: pd.DataFrame | None) -> None:
    if frame is None or frame.empty:
        st.info("NSE sector close report was unavailable for this date.")
        return
    name = next((col for col in ("Index Name", "Index") if col in frame), None)
    change = next((col for col in ("Change(%)", "Change %", "% Change") if col in frame), None)
    if not name or not change:
        st.dataframe(frame, width="stretch")
        return
    data = frame[[name, change]].copy()
    data[change] = pd.to_numeric(data[change], errors="coerce")
    data = data.dropna().sort_values(change)
    fig = go.Figure(go.Bar(x=data[change], y=data[name], orientation="h",
                           marker_color=["#dc5a59" if value < 0 else "#22a06b" for value in data[change]]))
    fig.update_layout(height=max(450, len(data) * 22), xaxis_title="Daily change (%)", yaxis_title="")
    st.plotly_chart(fig, width="stretch")


with st.sidebar:
    st.header("Data source")
    source = st.selectbox("Source", ["NSE derivatives", "US options · MarketData.app", "Upload CSV / NSE ZIP"])
    trade_date = st.date_input("Trade date", value=safe_default_date(source), max_value=date.today(),
                               key=f"date_{source}")
    symbol_input = ""
    token = ""
    upload = None
    if source.startswith("US"):
        choices = us_stock_options()
        default = next((i for i, label in enumerate(choices) if label.startswith("META —")), 0)
        selected_us = st.selectbox(
            "US stock or ETF", choices, index=default, accept_new_options=True,
            filter_mode="contains",
            placeholder="Type a ticker or company name",
            help="Start typing to filter the list. Press Enter to use a ticker missing from it.",
        )
        symbol_input = selected_us.split(" — ", 1)[0].strip().upper() if selected_us else ""
        token = st.text_input("Your MarketData.app API token", type="password",
                              help="Each user enters their own token. The app does not use a shared server token.")
    elif source.startswith("Upload"):
        upload = st.file_uploader("Option-chain CSV or NSE ZIP", type=["csv", "zip"])
        st.caption("CSV needs symbol, expiration, side, strike, option_price, volume, open_interest. MarketData.app and NSE exports are also recognized.")
    fetch = st.button("Load data", type="primary", width="stretch")

if fetch:
    try:
        with st.spinner("Loading option contracts…"):
            if source == "NSE derivatives":
                chain, references = download_nse(trade_date)
                fii, sectors = download_nse_context(trade_date)
            elif source.startswith("US"):
                if not symbol_input:
                    raise ValueError("Enter a US symbol.")
                if not token:
                    raise ValueError("Enter your own MarketData.app API token.")
                chain, references = download_us(symbol_input, trade_date, token), {}
                fii, sectors = None, None
            else:
                if upload is None:
                    raise ValueError("Select a CSV or ZIP file.")
                chain, references = normalize_upload(upload.getvalue(), upload.name)
                fii, sectors = None, None
            st.session_state["loaded"] = {
                "chain": chain, "references": references, "fii": fii, "sectors": sectors,
                "trade_date": trade_date, "source": source,
                "requested_symbol": symbol_input if source.startswith("US") else None,
            }
            st.session_state.pop("analysis", None)
        st.success(f"Loaded {len(chain):,} option contracts across {chain['symbol'].nunique()} symbols.")
    except Exception as exc:
        st.error(str(exc))

loaded = st.session_state.get("loaded")
if not loaded:
    st.info("Choose a source and trade date, then select **Load data**.")
    st.stop()
if (loaded["source"] != source or loaded["trade_date"] != trade_date
        or (source.startswith("US") and loaded.get("requested_symbol") != symbol_input)):
    st.info("The source, trade date, or symbol changed. Select **Load data** to analyze the new selection.")
    st.stop()

chain = loaded["chain"]
actual_date = loaded["trade_date"]
st.subheader("Select instrument")
c1, c2, c3 = st.columns(3)
symbols = sorted(chain["symbol"].unique())
default_symbol = "NIFTY" if "NIFTY" in symbols else ("META" if "META" in symbols else symbols[0])
with c1:
    selected_symbol = st.selectbox("Underlying", symbols, index=symbols.index(default_symbol))
subset = chain[chain["symbol"] == selected_symbol]
expiries = sorted(subset["expiration"].unique())
with c2:
    selected_expiry = st.selectbox("Expiry", expiries, format_func=lambda value: value.isoformat())
expiry_chain = subset[subset["expiration"] == selected_expiry]
auto_ref = future_reference(loaded["references"], selected_symbol, selected_expiry)
if auto_ref is None and "underlying_price" in expiry_chain:
    values = expiry_chain["underlying_price"].dropna()
    auto_ref = float(values.median()) if not values.empty else None
with c3:
    reference_price = st.number_input("Reference underlying / futures price", min_value=0.0,
                                      value=float(auto_ref or 0), step=0.01,
                                      help="NSE uses the matching futures close where available; US uses the chain's underlying price. You can override it.")
if auto_ref is None:
    st.warning("No reference price was found in the data. Enter it above to run the analysis.")

with st.expander("Analysis settings", expanded=False):
    a, b, c = st.columns(3)
    with a:
        iv = st.number_input("Simulated IV (%)", min_value=0.1, max_value=500.0,
                             value=15.0 if loaded["source"] == "NSE derivatives" else 25.0, step=1.0)
        rate = st.number_input("Risk-free rate (%)", min_value=0.0, max_value=50.0,
                               value=10.0 if loaded["source"] == "NSE derivatives" else 4.0, step=0.25)
    with b:
        min_volume = st.number_input("Minimum daily contract volume", min_value=0, max_value=10_000_000,
                                     value=500 if loaded["source"] == "NSE derivatives" else 0, step=100)
        dynamic_atm = st.checkbox("Closest listed strike as ATM", value=True)
        strike_step = st.number_input("ATM floor step", min_value=0.01, value=100.0, step=1.0,
                                      disabled=dynamic_atm)
    with c:
        iv_targets = st.checkbox("IV-based expected-move targets", value=True)
        fixed_percent = st.number_input("Fixed target distance (%)", min_value=0.1, max_value=100.0,
                                        value=2.5, step=0.1, disabled=iv_targets)
    st.caption("Greeks and ITM probabilities are model estimates using your IV and rate. The analysis uses the option mid price for US chains when available, and the close for NSE.")

if st.button(f"Analyze {selected_symbol}", type="primary"):
    try:
        settings = Settings(iv, rate, min_volume, dynamic_atm, strike_step, iv_targets, fixed_percent)
        result = analyze(chain, selected_symbol, selected_expiry, actual_date, reference_price, settings)
        st.session_state["analysis"] = (selected_symbol, selected_expiry, result, settings)
    except ValueError as exc:
        st.error(str(exc))

saved = st.session_state.get("analysis")
if saved and saved[0] == selected_symbol and saved[1] == selected_expiry:
    _, _, result, settings = saved
    st.caption(f"{selected_symbol} · {actual_date.isoformat()} · expiry {selected_expiry.isoformat()} · {result['after_filter']:,} of {result['before_filter']:,} contracts after volume filter")
    metrics = st.columns(5)
    metrics[0].metric("Reference", fmt(result["reference_price"]))
    metrics[1].metric("ATM strike", fmt(result["atm"]))
    metrics[2].metric("Max pain", fmt(result["max_pain"]))
    metrics[3].metric("Put/call OI", fmt(result["pcr_oi"]))
    metrics[4].metric("Put/call volume", fmt(result["pcr_volume"]))
    targets = st.columns(4)
    targets[0].metric("Lower target", fmt(result["lower"]))
    targets[1].metric("Upper target", fmt(result["upper"]))
    targets[2].metric("Support 1 / 2", f"{fmt(result['support_1'])} / {fmt(result['support_2'])}")
    targets[3].metric("Resistance 1 / 2", f"{fmt(result['resistance_1'])} / {fmt(result['resistance_2'])}")

    chart_data = result["chain"].pivot_table(index="strike", columns="side", values="open_interest", aggfunc="sum", fill_value=0)
    fig = go.Figure()
    for side, color in (("call", "#5470c6"), ("put", "#ee7c59")):
        if side in chart_data:
            fig.add_bar(x=chart_data.index, y=chart_data[side], name=side.title(), marker_color=color)
    fig.add_vline(x=result["reference_price"], line_dash="dash", line_color="#333",
                  annotation_text="Reference")
    fig.update_layout(barmode="group", title="Open interest by strike", xaxis_title="Strike",
                      yaxis_title="Contracts", height=430)
    st.plotly_chart(fig, width="stretch")

    tab_call, tab_put, tab_chain, tab_context = st.tabs(["Call resistance", "Put support", "Full chain & Greeks", "Market context"])
    shown = ["contract", "strike", "option_price", "volume", "open_interest", "premium_weighted_oi",
             "range", "distance_to_target", "delta", "theta_per_day", "model_prob_itm"]
    with tab_call:
        st.caption("Top 20 contracts by open interest × option price, ranked by distance to upper target.")
        st.dataframe(result["calls"][[c for c in shown if c in result["calls"]]],
                     width="stretch", hide_index=True)
    with tab_put:
        st.caption("Top 20 contracts by open interest × option price, ranked by distance to lower target.")
        st.dataframe(result["puts"][[c for c in shown if c in result["puts"]]],
                     width="stretch", hide_index=True)
    with tab_chain:
        st.dataframe(result["chain"].sort_values(["strike", "side"]), width="stretch", hide_index=True)
        st.download_button("Download analyzed chain CSV", result["chain"].to_csv(index=False).encode(),
                           file_name=f"{selected_symbol}_{actual_date.isoformat()}_{selected_expiry.isoformat()}_analysis.csv",
                           mime="text/csv")
    with tab_context:
        if loaded["source"] == "NSE derivatives":
            st.markdown("#### Participant positioning")
            show_smart_money(loaded["fii"])
            st.markdown("#### Sector performance")
            show_sectors(loaded["sectors"])
        else:
            st.info("NSE participant and sector reports apply only to NSE data.")

    st.caption("Max pain, expected move, and support/resistance are chain-based estimates. Historical US open interest is published before the selected session; option prices and volume are end-of-day. Historical IV/Greeks are not supplied by MarketData.app, so this app simulates them from your settings.")
