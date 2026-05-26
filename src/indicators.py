"""Calcolo dei 9 indicatori del composite.

Input: dict di DataFrame restituito da fetchers.fetch_all().
Output: DataFrame indicizzato per data con una colonna per indicatore +
        DataFrame "snapshot" con l'ultimo valore di ciascuno.

Indicatori:
    pi_cycle      → 111DMA / (350DMA × 2)        — top trigger >= 0.95
    mayer         → close / 200DMA                — top >2.4, bottom <1.0
    two_year_ma   → close / 2YMA                  — top >4 (banda rossa), bottom <1
    mvrv_z        → da bitcoin-data.com
    rsi_weekly    → RSI 14 settimanale            — top >85, bottom <35
    nupl          → da bitcoin-data.com
    puell         → da bitcoin-data.com
    hash_ribbons  → 30D hash rate / 60D hash rate — buy quando cross >1 dopo capitolazione
    bmsb          → close / midpoint(20WSMA, 21WEMA) — banda di supporto bull market
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1 / length, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / length, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_price_indicators(price: pd.DataFrame) -> pd.DataFrame:
    df = price[["date", "close"]].copy().sort_values("date").reset_index(drop=True)
    df["dma_111"] = df["close"].rolling(111).mean()
    df["dma_200"] = df["close"].rolling(200).mean()
    df["dma_350x2"] = df["close"].rolling(350).mean() * 2
    df["pi_cycle"] = df["dma_111"] / df["dma_350x2"]
    df["mayer"] = df["close"] / df["dma_200"]

    df["dma_730"] = df["close"].rolling(365 * 2).mean()
    df["two_year_ma"] = df["close"] / df["dma_730"]

    weekly = df.set_index("date")["close"].resample("W-MON").last()
    rsi_w = _rsi(weekly, 14)
    rsi_daily = rsi_w.reindex(df["date"], method="ffill").values
    df["rsi_weekly"] = rsi_daily

    sma_20w = weekly.rolling(20).mean()
    ema_21w = weekly.ewm(span=21, adjust=False).mean()
    bmsb_mid = ((sma_20w + ema_21w) / 2).reindex(df["date"], method="ffill").values
    df["bmsb_mid"] = bmsb_mid
    df["bmsb"] = df["close"] / df["bmsb_mid"]

    return df


def compute_hash_ribbons(hash_rate: pd.DataFrame) -> pd.DataFrame:
    df = hash_rate.copy().sort_values("date").reset_index(drop=True)
    df["hr_30"] = df["hash_rate"].rolling(30).mean()
    df["hr_60"] = df["hash_rate"].rolling(60).mean()
    df["hash_ribbons"] = df["hr_30"] / df["hr_60"]
    df["hr_cross_buy"] = (
        (df["hash_ribbons"] > 1.0)
        & (df["hash_ribbons"].shift(1) <= 1.0)
    )
    return df[["date", "hash_ribbons", "hr_cross_buy"]]


def merge_onchain(price_idx: pd.DataFrame, onchain: dict) -> pd.DataFrame:
    df = price_idx.copy()
    for name in ("mvrv_z", "nupl", "puell"):
        oc = onchain[name][["date", "value"]].rename(columns={"value": name})
        oc["date"] = pd.to_datetime(oc["date"])
        df = df.merge(oc, on="date", how="left")
    return df


def build_indicators(data: dict) -> pd.DataFrame:
    price_ind = compute_price_indicators(data["price"])
    hash_ind = compute_hash_ribbons(data["hash_rate"])
    df = price_ind.merge(hash_ind, on="date", how="left")
    df = merge_onchain(df, data)
    return df


def snapshot(df: pd.DataFrame) -> dict:
    """Restituisce gli ultimi valori non-NaN per ciascun indicatore + close."""
    cols = ["close", "pi_cycle", "mayer", "two_year_ma", "rsi_weekly",
            "bmsb", "hash_ribbons", "hr_cross_buy", "mvrv_z", "nupl", "puell"]
    snap = {}
    last = df.iloc[-1]
    snap["date"] = last["date"].date().isoformat()
    for c in cols:
        v = df[c].dropna().iloc[-1] if df[c].dropna().size else None
        snap[c] = float(v) if isinstance(v, (int, float, np.floating)) and not pd.isna(v) else (bool(v) if isinstance(v, (bool, np.bool_)) else None)
    return snap


if __name__ == "__main__":
    from .fetchers import fetch_all
    data = fetch_all()
    ind = build_indicators(data)
    snap = snapshot(ind)
    print("\n=== SNAPSHOT ===")
    for k, v in snap.items():
        if isinstance(v, float):
            print(f"  {k:15s}: {v:.4f}")
        else:
            print(f"  {k:15s}: {v}")
