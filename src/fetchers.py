"""Fetcher dei dati BTC da fonti pubbliche gratuite.

Fonti:
- Binance public API → prezzo daily BTCUSDT (dal 2017)
- bitcoin-data.com → MVRV Z-Score, NUPL, Puell, RHODL, Reserve Risk (dal 2022)
- Blockchain.info → hash rate

Tutti i dati vengono persistiti in data/cache/*.csv. Le successive run
fanno fetching incrementale solo per le date mancanti.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .config import CACHE_DIR

BINANCE_BASE = "https://api.binance.com/api/v3/klines"
BINANCE_SYMBOL = "BTCUSDT"
BINANCE_START_MS = 1502928000000  # 2017-08-17, primo giorno trading BTCUSDT

BITCOIN_DATA_BASE = "https://bitcoin-data.com/api/v1"
BITCOIN_DATA_METRICS = {
    "mvrv_z":       ("mvrv-zscore",     "mvrvZscore"),
    "nupl":         ("nupl",            "nupl"),
    "puell":        ("puell-multiple",  "puellMultiple"),
    "rhodl":        ("rhodl-ratio",     "rhodlRatio"),
}

BLOCKCHAIN_HASH_URL = "https://api.blockchain.info/charts/hash-rate?timespan=10years&format=json"

HEADERS = {"User-Agent": "btc-composite-tool/1.0"}


def _http_get_json(url: str, params: Optional[dict] = None, retries: int = 5, timeout: int = 30):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 2 ** attempt + 2))
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def fetch_btc_price_daily(force: bool = False) -> pd.DataFrame:
    """Scarica klines daily BTCUSDT da Binance, paginato 1000 candle alla volta.

    Cache: data/cache/binance_btc_daily.csv. Ad ogni run scarica solo le
    candele dopo l'ultima salvata.
    """
    cache = CACHE_DIR / "binance_btc_daily.csv"
    if cache.exists() and not force:
        df = pd.read_csv(cache, parse_dates=["date"])
        last_ts = int(df["date"].max().timestamp() * 1000) + 86_400_000
    else:
        df = pd.DataFrame()
        last_ts = BINANCE_START_MS

    now_ms = int(time.time() * 1000)
    new_rows = []
    while last_ts < now_ms:
        chunk = _http_get_json(
            BINANCE_BASE,
            params={
                "symbol": BINANCE_SYMBOL,
                "interval": "1d",
                "startTime": last_ts,
                "limit": 1000,
            },
        )
        if not chunk:
            break
        for row in chunk:
            new_rows.append({
                "date": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).date(),
                "open": float(row[1]),
                "high": float(row[2]),
                "low":  float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
        last_ts = chunk[-1][0] + 86_400_000
        if len(chunk) < 1000:
            break
        time.sleep(0.15)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        new_df["date"] = pd.to_datetime(new_df["date"])
        df = pd.concat([df, new_df], ignore_index=True).drop_duplicates("date").sort_values("date")
        df.to_csv(cache, index=False)

    df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True)


def fetch_bitcoin_data_metric(name: str, force: bool = False) -> pd.DataFrame:
    """Scarica una metrica on-chain da bitcoin-data.com.

    name: chiave interna ('mvrv_z', 'nupl', ...). Vedi BITCOIN_DATA_METRICS.
    """
    if name not in BITCOIN_DATA_METRICS:
        raise ValueError(f"Metrica sconosciuta: {name}")
    slug, json_key = BITCOIN_DATA_METRICS[name]
    cache = CACHE_DIR / f"bitcoin_data_{name}.csv"

    if cache.exists() and not force:
        cached = pd.read_csv(cache, parse_dates=["date"])
        last_date = cached["date"].max().date()
        if last_date >= datetime.now(timezone.utc).date():
            return cached

    raw = _http_get_json(f"{BITCOIN_DATA_BASE}/{slug}")
    if not raw:
        if cache.exists():
            return pd.read_csv(cache, parse_dates=["date"])
        raise RuntimeError(f"Impossibile scaricare {slug}")

    df = pd.DataFrame([
        {"date": item["d"], "value": item.get(json_key)}
        for item in raw if item.get(json_key) is not None
    ])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def fetch_hash_rate(force: bool = False) -> pd.DataFrame:
    """Hash rate giornaliero da Blockchain.info."""
    cache = CACHE_DIR / "blockchain_hash_rate.csv"
    if cache.exists() and not force:
        cached = pd.read_csv(cache, parse_dates=["date"])
        last_date = cached["date"].max().date()
        if (datetime.now(timezone.utc).date() - last_date).days < 1:
            return cached

    raw = _http_get_json(BLOCKCHAIN_HASH_URL)
    points = raw.get("values", []) if raw else []
    df = pd.DataFrame([
        {"date": datetime.fromtimestamp(p["x"], tz=timezone.utc).date(), "hash_rate": p["y"]}
        for p in points
    ])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def fetch_all(force: bool = False) -> dict:
    """Pipeline complessiva: scarica tutto e restituisce un dict di DataFrame."""
    print("[fetch] prezzo BTC daily da Binance...")
    price = fetch_btc_price_daily(force=force)
    print(f"  {len(price)} candle, da {price['date'].min().date()} a {price['date'].max().date()}")

    metrics = {}
    for name in BITCOIN_DATA_METRICS:
        print(f"[fetch] {name} da bitcoin-data.com...")
        metrics[name] = fetch_bitcoin_data_metric(name, force=force)
        print(f"  {len(metrics[name])} righe")
        time.sleep(2.0)  # rispetta rate limit bitcoin-data.com

    print("[fetch] hash rate da Blockchain.info...")
    hash_rate = fetch_hash_rate(force=force)
    print(f"  {len(hash_rate)} righe")

    return {"price": price, "hash_rate": hash_rate, **metrics}


if __name__ == "__main__":
    fetch_all()
