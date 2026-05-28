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

    # 200-week MA: divisore macro Bull/Bear classico
    sma_200w = weekly.rolling(200).mean()
    df["sma_200w"] = sma_200w.reindex(df["date"], method="ffill").values

    return df


def compute_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Bull/Bear regime macro.

    Divisore primario = media a 200 settimane (il classico spartiacque di ciclo):
      BULL  = prezzo sopra la 200WMA
      BEAR  = prezzo sotto la 200WMA
    Sotto-stato "in correzione" = prezzo sotto la Bull Market Support Band (20W/21W),
    cioè debolezza di medio termine dentro un trend.
    """
    df = df.copy()
    above_200w = df["close"] > df["sma_200w"]
    above_bmsb = df["close"] > df["bmsb_mid"]
    df["regime"] = np.where(above_200w, "BULL", "BEAR")
    df["regime_correction"] = above_200w & ~above_bmsb  # bull ma sotto la banda
    return df


def _find_pivots(series: pd.Series, lbL: int = 5, lbR: int = 5, kind: str = "low") -> list[int]:
    """Indici dei pivot (low o high) confermati: estremo locale con lbL barre a
    sinistra e lbR a destra. Replica ta.pivotlow/ta.pivothigh di Pine."""
    vals = series.values
    n = len(vals)
    out = []
    for i in range(lbL, n - lbR):
        window = vals[i - lbL: i + lbR + 1]
        if np.isnan(vals[i]) or np.isnan(window).any():
            continue
        if kind == "low" and vals[i] == window.min() and (window.min() < window[:lbL].min() or True):
            # confermato come minimo locale stretto
            if vals[i] <= window.min():
                out.append(i)
        elif kind == "high" and vals[i] >= window.max():
            out.append(i)
    # dedup pivots troppo vicini (tieni il primo di una run)
    cleaned = []
    for idx in out:
        if cleaned and idx - cleaned[-1] <= lbR:
            continue
        cleaned.append(idx)
    return cleaned


def compute_rsi_divergences(price: pd.DataFrame, lbL: int = 5, lbR: int = 5,
                            range_lower: int = 5, range_upper: int = 60) -> pd.DataFrame:
    """Divergenze RSI sul WEEKLY (logica dell'RSI Divergence Indicator di TradingView).

    Regular Bullish : prezzo Lower-Low  + RSI Higher-Low  → possibile reversal UP
    Regular Bearish : prezzo Higher-High + RSI Lower-High  → possibile reversal DOWN

    Restituisce DataFrame con [date, type] (type in {bull, bear}).
    """
    p = price[["date", "close", "high", "low"]].copy().sort_values("date").reset_index(drop=True)
    weekly = p.set_index("date").resample("W-MON").agg(
        {"close": "last", "high": "max", "low": "min"}
    ).dropna()
    rsi = _rsi(weekly["close"], 14)

    pl = _find_pivots(rsi, lbL, lbR, "low")
    ph = _find_pivots(rsi, lbL, lbR, "high")

    events = []
    # Regular Bullish: confronta pivot low consecutivi dell'RSI
    for a, b in zip(pl, pl[1:]):
        gap = b - a
        if not (range_lower <= gap <= range_upper):
            continue
        rsi_hl = rsi.iloc[b] > rsi.iloc[a]
        price_ll = weekly["low"].iloc[b] < weekly["low"].iloc[a]
        if rsi_hl and price_ll:
            events.append({"date": weekly.index[b], "type": "bull"})

    # Regular Bearish: confronta pivot high consecutivi dell'RSI
    for a, b in zip(ph, ph[1:]):
        gap = b - a
        if not (range_lower <= gap <= range_upper):
            continue
        rsi_lh = rsi.iloc[b] < rsi.iloc[a]
        price_hh = weekly["high"].iloc[b] > weekly["high"].iloc[a]
        if rsi_lh and price_hh:
            events.append({"date": weekly.index[b], "type": "bear"})

    if not events:
        return pd.DataFrame(columns=["date", "type"])
    return pd.DataFrame(events).sort_values("date").reset_index(drop=True)


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
    price_ind = compute_regime(price_ind)
    hash_ind = compute_hash_ribbons(data["hash_rate"])
    df = price_ind.merge(hash_ind, on="date", how="left")
    df = merge_onchain(df, data)
    return df


def snapshot(df: pd.DataFrame, divergences: pd.DataFrame | None = None) -> dict:
    """Restituisce gli ultimi valori non-NaN per ciascun indicatore + close + regime + divergenza."""
    cols = ["close", "pi_cycle", "mayer", "two_year_ma", "rsi_weekly",
            "bmsb", "hash_ribbons", "hr_cross_buy", "mvrv_z", "nupl", "puell"]
    snap = {}
    last = df.iloc[-1]
    snap["date"] = last["date"].date().isoformat()
    for c in cols:
        v = df[c].dropna().iloc[-1] if df[c].dropna().size else None
        snap[c] = float(v) if isinstance(v, (int, float, np.floating)) and not pd.isna(v) else (bool(v) if isinstance(v, (bool, np.bool_)) else None)

    # Regime macro (ultimo valore non-NaN)
    snap["regime"] = str(df["regime"].iloc[-1]) if "regime" in df else "BULL"
    snap["regime_correction"] = bool(df["regime_correction"].iloc[-1]) if "regime_correction" in df else False
    snap["sma_200w"] = float(df["sma_200w"].dropna().iloc[-1]) if df["sma_200w"].dropna().size else None

    # Ultima divergenza RSI (entro le ultime 6 settimane = ~42 giorni)
    snap["last_divergence"] = None
    snap["last_divergence_date"] = None
    snap["last_divergence_age_days"] = None
    if divergences is not None and not divergences.empty:
        last_div = divergences.iloc[-1]
        age = (pd.to_datetime(snap["date"]) - pd.to_datetime(last_div["date"])).days
        if age <= 42:
            snap["last_divergence"] = str(last_div["type"])
            snap["last_divergence_date"] = pd.to_datetime(last_div["date"]).date().isoformat()
            snap["last_divergence_age_days"] = int(age)
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
