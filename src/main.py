"""Entry-point della pipeline giornaliera.

Usage:
    python -m src.main                    # esegue tutto: fetch, calcola, backfill, dashboard, Telegram
    python -m src.main --no-telegram
    python -m src.main --no-fetch         # usa solo cache locale
    python -m src.main --no-backfill      # salta ricalcolo storico (più veloce)
"""
from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime

import pandas as pd

warnings.filterwarnings("ignore")

from .config import DATA_DIR
from .fetchers import fetch_all, fetch_btc_price_daily, fetch_hash_rate, fetch_bitcoin_data_metric, BITCOIN_DATA_METRICS
from .indicators import build_indicators, snapshot, compute_rsi_divergences
from .composite import composite_score, compute_history
from .reporter import build_dashboard
from . import telegram_bot


HISTORY_FILE = DATA_DIR / "composite_history.csv"


def load_history() -> pd.DataFrame:
    if HISTORY_FILE.exists():
        return pd.read_csv(HISTORY_FILE, parse_dates=["date"])
    return pd.DataFrame(columns=["date", "btc_close", "composite_score", "signal", "target_btc_exposure_pct"])


def save_history(history: pd.DataFrame) -> None:
    history.sort_values("date").to_csv(HISTORY_FILE, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-backfill", action="store_true")
    args = parser.parse_args()

    print(f"=== BTC Composite Indicator — {datetime.utcnow().date()} ===\n")

    if args.no_fetch:
        data = {
            "price": fetch_btc_price_daily(force=False),
            "hash_rate": fetch_hash_rate(force=False),
            **{k: fetch_bitcoin_data_metric(k, force=False) for k in BITCOIN_DATA_METRICS},
        }
    else:
        data = fetch_all()

    ind_df = build_indicators(data)
    divergences = compute_rsi_divergences(data["price"])
    snap = snapshot(ind_df, divergences=divergences)

    # Storico (con isteresi sequenziale). Serve PRIMA del segnale di oggi
    # perché l'isteresi dipende dal segnale di ieri.
    if args.no_backfill and HISTORY_FILE.exists():
        history = pd.read_csv(HISTORY_FILE, parse_dates=["date"])
        prev_signal = str(history["signal"].iloc[-1]) if len(history) else None
        result = composite_score(snap, prev_signal=prev_signal)
        today_row = pd.DataFrame([{
            "date": pd.to_datetime(result["date"]),
            "btc_close": result["btc_close"],
            "composite_score": result["composite_score"],
            "signal": result["signal"],
            "target_btc_exposure_pct": result["target_btc_exposure_pct"],
            "red_count": result["red_count"],
            "green_count": result["green_count"],
        }])
        history = pd.concat([history, today_row]).drop_duplicates(subset=["date"], keep="last")
    else:
        print("[backfill] calcolo composite storico (con isteresi) per tutta la time series...")
        history = compute_history(ind_df)
        prev_signal = str(history["signal"].iloc[-2]) if len(history) >= 2 else None
        result = composite_score(snap, prev_signal=prev_signal)
        print(f"  → {len(history)} giorni, da {history['date'].min().date()} a {history['date'].max().date()}")

    # News + Fear&Greed (server-side, contesto esterno). Non far mai fallire la pipeline.
    try:
        from .news import fetch_news
        news = fetch_news()
        print(f"[news] sentiment {news['label']} · {len(news['items'])} notizie")
    except Exception as exc:  # noqa: BLE001
        print(f"[news] errore (ignorato): {exc}")
        news = None
    try:
        from .news import fetch_fear_greed
        fng = fetch_fear_greed()
        if fng.get("available"):
            print(f"[fng] Fear&Greed {fng['value']} ({fng['classification']})")
    except Exception as exc:  # noqa: BLE001
        print(f"[fng] errore (ignorato): {exc}")
        fng = None

    print(f"\n  Date              : {result['date']}")
    print(f"  BTC close         : ${result['btc_close']:,.0f}")
    print(f"  Composite score   : {result['composite_score']}/100")
    print(f"  Signal            : {result['signal']}")
    print(f"  Target BTC exp.   : {result['target_btc_exposure_pct']}%")
    print(f"  Red / Green zones : {result['red_count']} / {result['green_count']} (su 9)")

    save_history(history)
    print(f"[history] salvato: {HISTORY_FILE}")

    out_html = build_dashboard(result, ind_df, history=history, divergences=divergences, news=news, fng=fng)
    print(f"[dashboard] generata: {out_html}")

    json_out = DATA_DIR / "latest_snapshot.json"
    json_out.write_text(json.dumps(
        {**result,
         "indicators": {k: {**v, "value": (None if v["value"] is None else
                                            float(v["value"]) if not isinstance(v["value"], bool) else
                                            v["value"])}
                         for k, v in result["indicators"].items()}},
        default=str, indent=2))
    print(f"[snapshot] salvato: {json_out}")

    if not args.no_telegram:
        telegram_bot.send(result)

    return result


if __name__ == "__main__":
    main()
