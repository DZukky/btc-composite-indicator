"""Macro Sentiment & Breaking News — fetch RSS + sentiment a dizionario crypto.

Server-side: il cron scarica i feed 1×/giorno e "cuoce" le news nell'HTML.
Niente CORS, niente API key, niente JS lato client. Solo stdlib + requests.

Fonti RSS pubbliche (no auth):
- CoinDesk:     https://www.coindesk.com/arc/outboundfeeds/rss/
- Cointelegraph: https://cointelegraph.com/rss

Il sentiment è calcolato con un dizionario crypto-specifico sui titoli.
IMPORTANTE: è contesto informativo, NON entra nel composite score (le news
sono un cattivo timing signal). Vedi nota nel widget.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests

FEEDS = [
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; btc-composite-tool/1.0)"}

# Dizionario crypto-specifico per il sentiment dei titoli
BULLISH = {
    "rally", "rallies", "surge", "surges", "soar", "soars", "jump", "jumps",
    "rise", "rises", "rallying", "ath", "all-time high", "record high", "record",
    "adoption", "inflow", "inflows", "bullish", "gain", "gains", "breakout",
    "accumulation", "accumulate", "institutional", "approval", "approved",
    "upgrade", "partnership", "buy", "buying", "boom", "soaring", "tops",
    "milestone", "green", "moon", "outperform", "etf inflow", "rebound", "recovers",
}
BEARISH = {
    "crash", "crashes", "plunge", "plunges", "drop", "drops", "fall", "falls",
    "slump", "slumps", "selloff", "sell-off", "liquidation", "liquidations",
    "hack", "hacked", "exploit", "ban", "bans", "lawsuit", "charges", "fraud",
    "bearish", "decline", "declines", "dump", "dumps", "fear", "outflow",
    "outflows", "warning", "warns", "collapse", "bankruptcy", "scam", "down",
    "loss", "losses", "tumble", "tumbles", "sinks", "sink", "fud", "red", "bleed",
    "slides", "slide", "slid", "shed", "sheds", "shedding", "selloff", "weak",
    "weakness", "pressure", "fears", "risk", "slips", "slip", "retreat",
}

WORD_RE = re.compile(r"[a-z][a-z\-']+")


def _sentiment(title: str) -> str:
    """Classifica un titolo in bull/bear/neutral con dizionario crypto."""
    text = title.lower()
    words = set(WORD_RE.findall(text))
    bull = len(words & BULLISH) + sum(1 for kw in BULLISH if " " in kw and kw in text)
    bear = len(words & BEARISH) + sum(1 for kw in BEARISH if " " in kw and kw in text)
    if bull > bear:
        return "bull"
    if bear > bull:
        return "bear"
    return "neutral"


def _parse_feed(source: str, url: str, timeout: int = 15) -> list[dict]:
    """Scarica e parsa un feed RSS 2.0. Ritorna [] in caso di errore (graceful)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as exc:  # noqa: BLE001
        print(f"[news] {source} non disponibile: {exc}")
        return []

    items = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        date_el = item.find("pubDate")
        if title_el is None or not (title_el.text or "").strip():
            continue
        title = title_el.text.strip()
        link = (link_el.text or "").strip() if link_el is not None else ""
        published = None
        if date_el is not None and date_el.text:
            try:
                published = parsedate_to_datetime(date_el.text)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                published = None
        items.append({
            "title": title,
            "link": link,
            "source": source,
            "published": published,
            "sentiment": _sentiment(title),
        })
    return items


def fetch_news(top_n: int = 5) -> dict:
    """Aggrega le news dai feed e calcola il sentiment globale.

    Ritorna dict:
      {
        "items": [{title, link, source, published, sentiment}, ...] (top_n, più recenti),
        "bull_pct", "bear_pct", "neutral_pct": int,
        "label": "Bullish"/"Bearish"/"Neutrale",
        "total": int (notizie analizzate),
        "available": bool,
      }
    """
    all_items = []
    for source, url in FEEDS:
        all_items.extend(_parse_feed(source, url))

    if not all_items:
        return {"items": [], "bull_pct": 0, "bear_pct": 0, "neutral_pct": 0,
                "label": "n/d", "total": 0, "available": False}

    # ordina per data desc (le news senza data vanno in fondo)
    all_items.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)

    # sentiment globale sulle prime ~20 notizie (più rappresentativo dei soli top_n)
    sample = all_items[:20]
    n = len(sample)
    bull = sum(1 for it in sample if it["sentiment"] == "bull")
    bear = sum(1 for it in sample if it["sentiment"] == "bear")
    neu = n - bull - bear
    bull_pct = round(100 * bull / n)
    bear_pct = round(100 * bear / n)
    neutral_pct = 100 - bull_pct - bear_pct

    if bull_pct - bear_pct >= 10:
        label = "Bullish"
    elif bear_pct - bull_pct >= 10:
        label = "Bearish"
    else:
        label = "Neutrale"

    return {
        "items": all_items[:top_n],
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "neutral_pct": neutral_pct,
        "label": label,
        "total": n,
        "available": True,
    }


FNG_URL = "https://api.alternative.me/fng/?limit=8"
FNG_CLASS_IT = {
    "Extreme Fear":  "Paura estrema",
    "Fear":          "Paura",
    "Neutral":       "Neutrale",
    "Greed":         "Avidità",
    "Extreme Greed": "Avidità estrema",
}


def fetch_fear_greed() -> dict:
    """Crypto Fear & Greed Index (alternative.me, free, no auth).

    SENTIMENT ESTERNO al modello: 0 = paura estrema, 100 = avidità estrema.
    Lettura contrarian: paura = storicamente occasioni, avidità = cautela.
    """
    try:
        r = requests.get(FNG_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            return {"available": False}
        cur = data[0]
        value = int(cur["value"])
        klass = cur.get("value_classification", "")
        hist = [int(d["value"]) for d in data]  # [oggi, ieri, ...]
        # trend rispetto a ~7 giorni fa
        prev = hist[-1] if len(hist) > 1 else value
        delta = value - prev
        if delta >= 5:
            trend = f"in aumento (+{delta} in una settimana)"
        elif delta <= -5:
            trend = f"in calo ({delta} in una settimana)"
        else:
            trend = "stabile nell'ultima settimana"
        return {
            "available": True,
            "value": value,
            "classification": klass,
            "classification_it": FNG_CLASS_IT.get(klass, klass),
            "history": list(reversed(hist)),  # cronologico crescente
            "trend": trend,
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[fng] non disponibile: {exc}")
        return {"available": False}


def safe(text: str) -> str:
    """HTML-escape per evitare injection da titoli/link dei feed."""
    return html.escape(text or "", quote=True)


if __name__ == "__main__":
    data = fetch_news()
    print(f"Sentiment: {data['label']} (bull {data['bull_pct']}% · neu {data['neutral_pct']}% · bear {data['bear_pct']}%) su {data['total']} news")
    for it in data["items"]:
        d = it["published"].date() if it["published"] else "?"
        print(f"  [{it['sentiment']:7s}] {d} {it['source']}: {it['title'][:80]}")
