"""Composite score + position sizing.

Idea: per ciascun indicatore mappo il valore corrente in uno score 0-100
dove 0 = "fortemente buy / fondo ciclo", 100 = "fortemente sell / top ciclo".

Il mapping è una rampa lineare tra le soglie definite in INDICATOR_THRESHOLDS:
    val <= bot_green   → score 0
    val == bot_yellow  → score 25
    val == top_yellow  → score 75
    val >= top_red     → score 100
Tra le soglie interpolo linearmente.

Il composite è una somma pesata. Position sizing target = sigmoide del composite.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from .config import INDICATOR_WEIGHTS, INDICATOR_THRESHOLDS, COMPOSITE_TRIGGERS


def _ramp(val: float, points: list[tuple[float, float]]) -> float:
    """Interpolazione lineare attraverso una lista di (input, score) ordinata per input."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 50.0  # neutro se mancante
    pts = sorted(points, key=lambda p: p[0])
    if val <= pts[0][0]:
        return pts[0][1]
    if val >= pts[-1][0]:
        return pts[-1][1]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x1 <= val <= x2:
            t = (val - x1) / (x2 - x1) if x2 != x1 else 0.0
            return y1 + t * (y2 - y1)
    return 50.0


def score_indicator(name: str, value, hash_buy_cross: Optional[bool] = None) -> Optional[float]:
    t = INDICATOR_THRESHOLDS[name]

    if name == "hash_ribbons":
        if hash_buy_cross:
            return 5.0  # appena formato buy cross → strong bottom signal
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        # ratio 30/60 hash rate: <0.97 = miner capitulation in corso
        return _ramp(value, [(0.93, 10), (0.97, 30), (1.0, 50), (1.05, 65), (1.15, 80)])

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None

    points = []
    if t.get("bot_green") is not None:
        points.append((t["bot_green"], 0))
    if t.get("bot_yellow") is not None:
        points.append((t["bot_yellow"], 25))
    if t.get("top_yellow") is not None:
        points.append((t["top_yellow"], 75))
    if t.get("top_red") is not None:
        points.append((t["top_red"], 100))

    if name == "pi_cycle":
        # Asimmetrico: il "Pi Cycle TOP" individua i TOP, non i bottom.
        # Quando è basso significa solo "non siamo a un top" → neutro (50), non buy.
        # Contribuisce al segnale SELL solo avvicinandosi a 1.0.
        points = [(0.5, 50), (0.7, 55), (0.85, 75), (0.95, 95), (1.0, 100)]

    return _ramp(float(value), sorted(points, key=lambda p: p[0]))


def classify_zone(name: str, value, hash_buy_cross: Optional[bool] = None) -> str:
    s = score_indicator(name, value, hash_buy_cross)
    if s is None:
        return "n/a"
    if s >= 80:
        return "red"
    if s >= 65:
        return "orange"
    if s >= 35:
        return "neutral"
    if s >= 20:
        return "lime"
    return "green"


def composite_score(snap: dict) -> dict:
    per_ind = {}
    weighted_sum = 0.0
    weight_used = 0.0

    for name, weight in INDICATOR_WEIGHTS.items():
        val = snap.get(name)
        buy_cross = snap.get("hr_cross_buy") if name == "hash_ribbons" else None
        s = score_indicator(name, val, buy_cross)
        zone = classify_zone(name, val, buy_cross)
        per_ind[name] = {"value": val, "score": s, "zone": zone, "weight": weight}
        if s is not None:
            weighted_sum += s * weight
            weight_used += weight

    composite = weighted_sum / weight_used if weight_used > 0 else 50.0

    red_count = sum(1 for v in per_ind.values() if v["zone"] == "red")
    green_count = sum(1 for v in per_ind.values() if v["zone"] == "green")

    signal = "HOLD"
    if composite >= COMPOSITE_TRIGGERS["strong_sell"]["score_min"] and red_count >= COMPOSITE_TRIGGERS["strong_sell"]["agree_min"]:
        signal = "STRONG_SELL"
    elif composite <= COMPOSITE_TRIGGERS["strong_buy"]["score_max"] and green_count >= COMPOSITE_TRIGGERS["strong_buy"]["agree_min"]:
        signal = "STRONG_BUY"
    elif composite >= 65:
        signal = "DERISK"
    elif composite <= 35:
        signal = "ACCUMULATE"

    target_pct = 100.0 / (1 + math.exp((composite - 50) / 10.0))

    return {
        "date": snap["date"],
        "btc_close": snap.get("close"),
        "composite_score": round(composite, 2),
        "red_count": red_count,
        "green_count": green_count,
        "signal": signal,
        "target_btc_exposure_pct": round(target_pct, 1),
        "indicators": per_ind,
    }


def compute_history(ind_df) -> "pd.DataFrame":
    """Applica composite_score ad ogni riga della time series.

    Salta le righe in cui troppi indicatori sono NaN (es. inizio storia,
    quando le medie mobili lunghe non sono ancora calcolabili).
    """
    import pandas as pd

    snap_cols = ["pi_cycle", "mayer", "two_year_ma", "mvrv_z",
                 "rsi_weekly", "nupl", "puell", "hash_ribbons",
                 "hr_cross_buy", "bmsb", "close"]

    out = []
    for _, r in ind_df.iterrows():
        snap = {"date": r["date"].date().isoformat()}
        non_na = 0
        for c in snap_cols:
            v = r.get(c)
            if v is None:
                snap[c] = None
            elif isinstance(v, bool):
                snap[c] = bool(v)
            elif pd.isna(v):
                snap[c] = None
            else:
                snap[c] = float(v) if not isinstance(v, bool) else bool(v)
                if c != "close":
                    non_na += 1

        if non_na < 5:
            continue

        res = composite_score(snap)
        out.append({
            "date":                 pd.to_datetime(res["date"]),
            "btc_close":            res["btc_close"],
            "composite_score":      res["composite_score"],
            "signal":               res["signal"],
            "target_btc_exposure_pct": res["target_btc_exposure_pct"],
            "red_count":            res["red_count"],
            "green_count":          res["green_count"],
        })

    return pd.DataFrame(out)


SIGNAL_DESCRIPTIONS = {
    "STRONG_SELL": "Top di ciclo probabile. ≥4 indicatori in red zone, composite ≥80. Storicamente questa è la finestra di derisk massimo.",
    "DERISK":      "Mercato surriscaldato. Composite ≥70. Considera di ridurre esposizione progressivamente.",
    "HOLD":        "Zona neutra / trend follow. Mantieni esposizione coerente con il target di sizing.",
    "ACCUMULATE":  "Mercato sottovalutato. Composite ≤30. Considera di aumentare esposizione progressivamente.",
    "STRONG_BUY":  "Bottom di ciclo probabile. ≥4 indicatori in green zone, composite ≤20. Storicamente questa è la finestra di accumulazione massima.",
}


if __name__ == "__main__":
    from .fetchers import fetch_all
    from .indicators import build_indicators, snapshot
    data = fetch_all()
    ind = build_indicators(data)
    snap = snapshot(ind)
    result = composite_score(snap)
    print("\n=== COMPOSITE ===")
    print(f"  Date              : {result['date']}")
    print(f"  BTC close (USD)   : {result['btc_close']:.0f}")
    print(f"  Composite score   : {result['composite_score']}/100")
    print(f"  Red zones         : {result['red_count']} / {len(result['indicators'])}")
    print(f"  Green zones       : {result['green_count']} / {len(result['indicators'])}")
    print(f"  Signal            : {result['signal']}")
    print(f"  Target BTC exp.   : {result['target_btc_exposure_pct']}%")
    print("\n  Indicatori:")
    for name, info in result["indicators"].items():
        v = info["value"]
        v_str = f"{v:.4f}" if isinstance(v, (int, float)) and v is not None and not math.isnan(v) else str(v)
        s_str = f"{info['score']:.1f}" if info['score'] is not None else "n/a"
        print(f"    {name:14s} = {v_str:>10s}  score={s_str:>5s}  zone={info['zone']:8s}  w={info['weight']:.2f}")
