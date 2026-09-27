"""Source-independent end-of-day option-chain calculations."""

from dataclasses import dataclass
from datetime import date
from math import erf, floor, sqrt

import numpy as np
import pandas as pd


REQUIRED = ("symbol", "expiration", "side", "strike", "option_price", "volume", "open_interest")


@dataclass(frozen=True)
class Settings:
    iv_percent: float = 25.0
    risk_free_percent: float = 4.0
    min_volume: int = 0
    dynamic_atm: bool = True
    strike_step: float = 100.0
    iv_targets: bool = True
    fixed_target_percent: float = 2.5


def clean_chain(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED if column not in frame]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))
    df = frame.copy()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["expiration"] = pd.to_datetime(df["expiration"], errors="coerce").dt.date
    df["side"] = df["side"].astype(str).str.strip().str.lower().replace(
        {"ce": "call", "c": "call", "pe": "put", "p": "put"}
    )
    for column in ("strike", "option_price", "volume", "open_interest", "underlying_price", "bid", "ask"):
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df[df["side"].isin(("call", "put")) & df["expiration"].notna()]
    df = df[df["strike"].gt(0) & df["option_price"].ge(0)]
    df["volume"] = df["volume"].fillna(0).clip(lower=0)
    df["open_interest"] = df["open_interest"].fillna(0).clip(lower=0)
    if df.empty:
        raise ValueError("The chain has no valid call or put contracts with positive strikes and prices.")
    return df.reset_index(drop=True)


def _normal_cdf(values: np.ndarray) -> np.ndarray:
    return np.fromiter((0.5 * (1 + erf(float(x) / sqrt(2))) for x in values), dtype=float)


def max_pain(chain: pd.DataFrame) -> float:
    strikes = np.sort(chain["strike"].unique())
    calls = chain[chain["side"] == "call"]
    puts = chain[chain["side"] == "put"]
    call_loss = (np.maximum(strikes[:, None] - calls["strike"].to_numpy()[None, :], 0)
                 * calls["open_interest"].to_numpy()[None, :]).sum(axis=1)
    put_loss = (np.maximum(puts["strike"].to_numpy()[None, :] - strikes[:, None], 0)
                * puts["open_interest"].to_numpy()[None, :]).sum(axis=1)
    return float(strikes[np.argmin(call_loss + put_loss)])


def analyze(frame: pd.DataFrame, symbol: str, expiry: date, trade_date: date,
            reference_price: float, settings: Settings) -> dict:
    if reference_price <= 0:
        raise ValueError("Reference price must be positive.")
    if settings.iv_percent <= 0:
        raise ValueError("Simulated IV must be positive.")
    if expiry < trade_date:
        raise ValueError("Expiry precedes the trade date.")
    if not settings.dynamic_atm and settings.strike_step <= 0:
        raise ValueError("Strike step must be positive.")
    df = clean_chain(frame)
    df = df[(df["symbol"] == symbol.upper()) & (df["expiration"] == expiry)]
    before_filter = len(df)
    df = df[df["volume"] >= settings.min_volume].copy()
    if df.empty:
        raise ValueError("No contracts remain after selecting the symbol, expiry, and volume filter.")

    years = max((expiry - trade_date).days + 1, 1) / 365.0
    rate = settings.risk_free_percent / 100
    sigma = settings.iv_percent / 100
    strikes = df["strike"].to_numpy(dtype=float)
    d1 = (np.log(reference_price / strikes) + (rate + 0.5 * sigma**2) * years) / (sigma * np.sqrt(years))
    d2 = d1 - sigma * np.sqrt(years)
    n_d1, n_d2 = _normal_cdf(d1), _normal_cdf(d2)
    pdf_d1 = np.exp(-0.5 * d1**2) / np.sqrt(2 * np.pi)
    call = df["side"].eq("call").to_numpy()
    df["delta"] = np.where(call, n_d1, n_d1 - 1)
    df["theta_per_day"] = (
        -reference_price * sigma * pdf_d1 / (2 * np.sqrt(years))
        - np.where(call, 1, -1) * rate * strikes * np.exp(-rate * years)
        * np.where(call, n_d2, _normal_cdf(-d2))
    ) / 365
    df["model_prob_itm"] = np.where(call, n_d2, _normal_cdf(-d2)) * 100
    df["premium_weighted_oi"] = df["open_interest"] * df["option_price"]
    df["range"] = np.where(call, df["strike"] + df["option_price"],
                           df["strike"] - df["option_price"])

    if settings.dynamic_atm:
        atm = float(min(df["strike"].unique(), key=lambda strike: abs(strike - reference_price)))
    else:
        atm = floor(reference_price / settings.strike_step) * settings.strike_step
    if settings.iv_targets:
        move = max(reference_price * sigma * np.sqrt(years), reference_price * 0.005)
        lower, upper = atm - move, atm + move
    else:
        move = atm * settings.fixed_target_percent / 100
        if settings.dynamic_atm:
            lower, upper = atm - move, atm + move
        else:
            lower = floor((atm - move) / settings.strike_step) * settings.strike_step
            upper = floor((atm + move) / settings.strike_step) * settings.strike_step

    ce = df[df["side"] == "call"].copy()
    pe = df[df["side"] == "put"].copy()

    def ratio(numerator: float, denominator: float) -> float | None:
        return float(numerator / denominator) if denominator > 0 else None

    def ranked(contracts: pd.DataFrame, target: float) -> pd.DataFrame:
        pool = contracts.nlargest(20, "premium_weighted_oi").copy()
        pool["distance_to_target"] = (pool["range"] - target).abs()
        return pool.sort_values(["distance_to_target", "premium_weighted_oi"], ascending=[True, False])

    calls_ranked, puts_ranked = ranked(ce, upper), ranked(pe, lower)
    return {
        "chain": df, "calls": calls_ranked, "puts": puts_ranked,
        "reference_price": reference_price, "atm": atm, "max_pain": max_pain(df),
        "pcr_oi": ratio(pe["open_interest"].sum(), ce["open_interest"].sum()),
        "pcr_volume": ratio(pe["volume"].sum(), ce["volume"].sum()),
        "lower": lower, "upper": upper, "move": move,
        "support_1": float(puts_ranked.iloc[0]["range"]) if len(puts_ranked) else None,
        "support_2": float(puts_ranked.iloc[1]["range"]) if len(puts_ranked) > 1 else None,
        "resistance_1": float(calls_ranked.iloc[0]["range"]) if len(calls_ranked) else None,
        "resistance_2": float(calls_ranked.iloc[1]["range"]) if len(calls_ranked) > 1 else None,
        "before_filter": before_filter, "after_filter": len(df),
    }
