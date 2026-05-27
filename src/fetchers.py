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

CRYPTOCOMPARE_BASE = "https://min-api.cryptocompare.com/data/v2/histoday"
CRYPTOCOMPARE_FSYM = "BTC"
CRYPTOCOMPARE_TSYM = "USD"
CRYPTOCOMPARE_LIMIT = 2000  # max per call

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
    """Scarica daily BTC/USD da CryptoCompare (free, no geo-block, 2000 candele/call).

    Endpoint: GET /data/v2/histoday?fsym=BTC&tsym=USD&limit=2000&toTs=<unix>
    Response: {"Data": {"Data": [{"time","open","high","low","close","volumefrom",...}]}}
    Pagina all'indietro tramite toTs finché new_min < cached_max (o data minima fissa).
    """
    cache = CACHE_DIR / "cryptocompare_btc_daily.csv"
    cache_legacy = CACHE_DIR / "binance_btc_daily.csv"
    cache_legacy_kraken = CACHE_DIR / "kraken_btc_daily.csv"

    df = pd.DataFrame()
    if cache.exists() and not force:
        df = pd.read_csv(cache, parse_dates=["date"])
    elif cache_legacy_kraken.exists() and not force:
        df = pd.read_csv(cache_legacy_kraken, parse_dates=["date"])
    elif cache_legacy.exists() and not force:
        df = pd.read_csv(cache_legacy, parse_dates=["date"])

    have_until = int(df["date"].max().timestamp()) if not df.empty else 0
    target_min_ts = int(datetime(2014, 1, 1, tzinfo=timezone.utc).timestamp())
    to_ts = int(time.time())
    all_new = []

    while True:
        resp = _http_get_json(
            CRYPTOCOMPARE_BASE,
            params={
                "fsym": CRYPTOCOMPARE_FSYM,
                "tsym": CRYPTOCOMPARE_TSYM,
                "limit": CRYPTOCOMPARE_LIMIT,
                "toTs": to_ts,
            },
        )
        if not resp or resp.get("Response") == "Error":
            print(f"[cryptocompare] errore: {resp.get('Message') if resp else 'no response'}")
            break
        data = (resp.get("Data") or {}).get("Data") or []
        data = [d for d in data if d.get("close") and d["close"] > 0]
        if not data:
            break
        for d in data:
            all_new.append({
                "date":   datetime.fromtimestamp(d["time"], tz=timezone.utc).date(),
                "open":   float(d["open"]),
                "high":   float(d["high"]),
                "low":    float(d["low"]),
                "close":  float(d["close"]),
                "volume": float(d.get("volumefrom", 0)),
            })
        oldest = data[0]["time"]
        if oldest <= target_min_ts or oldest <= have_until:
            break
        to_ts = oldest - 86_400
        time.sleep(0.4)

    if all_new:
        new_df = pd.DataFrame(all_new)
        new_df["date"] = pd.to_datetime(new_df["date"])
        df = pd.concat([df, new_df], ignore_index=True).drop_duplicates("date").sort_values("date")
        df = df[df["date"] >= pd.Timestamp("2014-01-01")]
        df.to_csv(cache, index=False)

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True) if not df.empty else df


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
    print("[fetch] prezzo BTC daily da CryptoCompare...")
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
