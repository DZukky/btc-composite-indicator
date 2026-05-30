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

from .config import (INDICATOR_WEIGHTS, INDICATOR_THRESHOLDS, COMPOSITE_TRIGGERS,
                     DCA_MULT_MIN, DCA_MULT_MAX, DCA_RESERVE_CAP,
                     DCA_TIER_MULT, DCA_TIER_LADDER, DCA_PCT_WINDOW,
                     DCA_TIER_DWELL_DAYS, DCA_REGIME_OVERLAY, DCA_SMA_REGIME_DAYS,
                     DCA_PCT_AGGR, DCA_PCT_INCR, DCA_PCT_RID, DCA_PCT_MIN)


def apply_reserve(mult: float, reserve: float, cap: float = DCA_RESERVE_CAP) -> tuple[float, float]:
    """Flusso DCA. L'acquisto consigliato è SEMPRE il moltiplicatore del mercato (`mult`):
    BTC conveniente → >1, BTC caro → <1. Coerente al 100% col segnale.

    Il salvadanaio è un dato INFORMATIVO (non limita l'acquisto mostrato):
      - mult < 1 (BTC caro):        accantoni `(1 - mult)` → la riserva cresce (con tetto `cap`)
      - mult > 1 (BTC conveniente): l'extra `(mult - 1)` viene finanziato prima dalla riserva
                                    (prelievo = min(extra, reserve)), il resto da liquidità fresca.

    Ritorna (acquisto_consigliato, nuova_riserva), entrambi in multipli di cifra base.
    """
    if mult <= 1.0:
        reserve = min(cap, reserve + (1.0 - mult))
    else:
        draw = min(mult - 1.0, reserve)
        reserve -= draw
    return round(mult, 3), round(reserve, 3)


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


def decide_signal(composite: float, red_count: int, green_count: int,
                  prev_signal: str | None = None) -> str:
    """Decide il segnale con ISTERESI per ridurre lo sfarfallio vicino alle soglie.

    Soglie di ENTRATA nette; per restare in una fase si applica un margine (zona morta):
    una volta dentro, si esce solo se il composite supera la soglia di un margine M.
    Questo evita cambi-rumore quando il composite oscilla attorno a una soglia.
    """
    M = 5  # margine isteresi
    # STRONG_BUY: entra ≤20 & 4 green; resta ≤25 & ≥3 green
    if (composite <= 20 and green_count >= 4) or \
       (prev_signal == "STRONG_BUY" and composite <= 20 + M and green_count >= 3):
        return "STRONG_BUY"
    # STRONG_SELL: entra ≥80 & 4 red; resta ≥75 & ≥3 red
    if (composite >= 80 and red_count >= 4) or \
       (prev_signal == "STRONG_SELL" and composite >= 80 - M and red_count >= 3):
        return "STRONG_SELL"
    # ACCUMULATE: entra ≤35; resta ≤40
    acc_thr = 35 + M if prev_signal == "ACCUMULATE" else 35
    if composite <= acc_thr:
        return "ACCUMULATE"
    # DERISK: entra ≥65; resta ≥60
    der_thr = 65 - M if prev_signal == "DERISK" else 65
    if composite >= der_thr:
        return "DERISK"
    return "HOLD"


def composite_score(snap: dict, prev_signal: str | None = None) -> dict:
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

    # Conteggio "stretto" per i trigger (solo verde/rosso pieno)
    red_count = sum(1 for v in per_ind.values() if v["zone"] == "red")
    green_count = sum(1 for v in per_ind.values() if v["zone"] == "green")

    # Conteggio "display" che corrisponde ai badge mostrati all'utente:
    # verdi (green+lime)=favorevoli, rossi (red+orange)=negativi, grigio=neutri
    fav_count = sum(1 for v in per_ind.values() if v["zone"] in ("green", "lime"))
    neg_count = sum(1 for v in per_ind.values() if v["zone"] in ("red", "orange"))
    neu_count = sum(1 for v in per_ind.values() if v["zone"] == "neutral")

    signal = decide_signal(composite, red_count, green_count, prev_signal)

    target_pct = 100.0 / (1 + math.exp((composite - 50) / 10.0))

    # Moltiplicatore PROVVISORIO (fallback). Il valore vero è assegnato da
    # assign_dca_tiers() che usa il percentile mobile + isteresi: serve la storia,
    # qui non è disponibile. main.py/compute_history sovrascrivono signal+multiplier.
    dca_multiplier = DCA_TIER_MULT.get(signal, 1.0)

    # Consiglio DCA derivato dal composite (riusa i 9 indicatori, non solo la 200-SMA)
    dist200 = snap.get("dist_200d_pct")
    dist_txt = ""
    if dist200 is not None:
        verso = "sopra" if dist200 >= 0 else "sotto"
        dist_txt = f" Il prezzo è {abs(dist200):.0f}% {verso} la media a 200 giorni."
    if composite <= 35:
        dca = {
            "level": "SOSTENUTO",
            "reason": "Fase di accumulo favorevole su livelli storicamente solidi (composite basso)." + dist_txt,
            "bot_state": "ATTIVO",
            "bot_action": "Fase favorevole: puoi valutare di incrementare leggermente l'importo della singola ricorrenza "
                          "(ordine di grandezza +10-20%) mantenendo la stessa frequenza. Entità e decisione restano tue.",
        }
    elif composite >= 65:
        dca = {
            "level": "RIDOTTO",
            "reason": "BTC è esteso su più metriche (composite alto): conviene rallentare l'accumulo." + dist_txt,
            "bot_state": "ATTIVO",
            "bot_action": "Fase estesa: puoi valutare di ridurre l'importo della ricorrenza per non accumulare sui massimi "
                          "locali, oppure accantonare parte in liquidità di riserva. La scelta resta tua.",
        }
    else:
        dca = {
            "level": "DI ROUTINE",
            "reason": "Mercato in equilibrio: accumulo standard a quote costanti." + dist_txt,
            "bot_state": "ATTIVO",
            "bot_action": "Nessuna modifica necessaria: lascia correre l'automatismo secondo la tua pianificazione abituale.",
        }

    return {
        "date": snap["date"],
        "btc_close": snap.get("close"),
        "composite_score": round(composite, 2),
        "red_count": red_count,
        "green_count": green_count,
        "fav_count": fav_count,
        "neg_count": neg_count,
        "neu_count": neu_count,
        "signal": signal,
        "target_btc_exposure_pct": round(target_pct, 1),
        "dca_multiplier": round(dca_multiplier, 3),
        "indicators": per_ind,
        "regime": snap.get("regime", "BULL"),
        "regime_correction": snap.get("regime_correction", False),
        "sma_200w": snap.get("sma_200w"),
        "sma_200d": snap.get("sma_200d"),
        "dist_200d_pct": snap.get("dist_200d_pct"),
        "dca": dca,
        "last_divergence": snap.get("last_divergence"),
        "last_divergence_date": snap.get("last_divergence_date"),
        "last_divergence_age_days": snap.get("last_divergence_age_days"),
    }


def walk_forward_percentile(scores, win: int = DCA_PCT_WINDOW):
    """Rango percentile (0-100) di scores[t] nella finestra mobile [t-win+1 : t].

    WALK-FORWARD STRETTO: al giorno t usa SOLO dati <= t (nessun look-ahead).
    Espandente finché ci sono < win giorni, poi rolling a `win`.
    """
    import numpy as np
    s = np.asarray(scores, dtype=float)
    n = len(s)
    out = np.full(n, 50.0)
    for t in range(n):
        lo = max(0, t - win + 1)
        window = s[lo:t + 1]
        out[t] = float((window <= s[t]).mean() * 100.0)
    return out


def raw_tier(pct: float, composite: float, green: int, bear: bool) -> str:
    """Fascia 'istantanea' dal percentile + hybrid gate sugli estremi + overlay 200gg.

    Gli estremi (AGGRESSIVO/MINIMO) richiedono percentile estremo E conferma
    assoluta (e ≥4 verdi per l'AGGRESSIVO): evita di inventare segnali nei mercati
    piatti, dove il percentile da solo tratterebbe il minimo locale come 'occasione'.
    Se il gate non passa, si scala alla fascia adiacente meno estrema.
    """
    if pct <= DCA_PCT_AGGR and composite <= 35 and green >= 4:
        tier = "STRONG_BUY"
    elif pct <= DCA_PCT_INCR:
        tier = "ACCUMULATE"
    elif pct < DCA_PCT_RID:
        tier = "HOLD"
    elif pct >= DCA_PCT_MIN and composite >= 65:
        tier = "STRONG_SELL"
    elif pct >= DCA_PCT_RID:
        tier = "DERISK"
    else:
        tier = "HOLD"

    # Overlay di regime: sotto la media 200gg (zona di valore storica) sposta la
    # scala di UNA tacca verso l'accumulo. Unica regola di regime, parameter-free.
    # CAP: l'overlay può spingere al massimo fino ad ACCUMULATE — gli ESTREMI
    # (AGGRESSIVO/MINIMO) restano solo-gate, così l'overlay non fabbrica un estremo
    # spurio (es. composite 31 con 1 solo verde NON deve diventare 1.5×). Mai declassa.
    if bear and DCA_REGIME_OVERLAY:
        i = DCA_TIER_LADDER.index(tier)
        cap = DCA_TIER_LADDER.index("ACCUMULATE")
        tier = DCA_TIER_LADDER[max(i, min(i + 1, cap))]
    return tier


def assign_dca_tiers(history: "pd.DataFrame") -> "pd.DataFrame":
    """Assegna fascia DCA (=`signal`), moltiplicatore, percentile e riserva.

    Pipeline (sequenziale, deterministica → ricomputabile ogni giorno senza drift):
      1. percentile walk-forward del composite (4 anni)
      2. media 200gg dal prezzo → contesto bull/bear per l'overlay
      3. fascia istantanea (raw_tier) con hybrid gate + overlay
      4. PERMANENZA MINIMA: una volta in una fascia ci resti almeno
         DCA_TIER_DWELL_DAYS giorni prima di poter cambiare (stabilità: poche
         variazioni l'anno invece di sfarfallio quotidiano)
      5. moltiplicatore dalla fascia + salvadanaio informativo (apply_reserve)
    """
    import numpy as np
    import pandas as pd

    h = history.sort_values("date").reset_index(drop=True).copy()
    scores = h["composite_score"].values
    pct = walk_forward_percentile(scores)
    close = h["btc_close"].values
    sma = pd.Series(close).rolling(DCA_SMA_REGIME_DAYS, min_periods=1).mean().values
    green = h["green_count"].values if "green_count" in h else np.zeros(len(h))

    levels, mults, buys, reserves = [], [], [], []
    cur, days_in, reserve = None, 0, 0.0
    for i in range(len(h)):
        bear = bool(close[i] < sma[i])
        proposed = raw_tier(float(pct[i]), float(scores[i]), int(green[i]), bear)
        if cur is None:
            cur, days_in = proposed, 0
        elif proposed != cur and days_in >= DCA_TIER_DWELL_DAYS:
            cur, days_in = proposed, 0
        else:
            days_in += 1
        mult = DCA_TIER_MULT[cur]
        buy, reserve = apply_reserve(mult, reserve)
        levels.append(cur); mults.append(mult); buys.append(buy); reserves.append(reserve)

    h["signal"] = levels
    h["dca_percentile"] = np.round(pct, 1)
    h["dca_multiplier"] = mults
    h["dca_buy_factor"] = buys
    h["reserve_balance"] = np.round(reserves, 3)
    return h


def compute_history(ind_df) -> "pd.DataFrame":
    """Costruisce la time series del composite, poi assegna le fasce DCA a percentile.

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
            "target_btc_exposure_pct": res["target_btc_exposure_pct"],
            "red_count":            res["red_count"],
            "green_count":          res["green_count"],
        })

    # Fasce DCA (signal, moltiplicatore, percentile, riserva) calcolate sulla serie completa.
    return assign_dca_tiers(pd.DataFrame(out))


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
