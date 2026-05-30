"""Confronto onesto di TUTTE le versioni del modulatore DCA vs comprare e basta.

Strategie:
  0. PIATTO            — compra sempre la stessa cifra (la cosa piu' semplice)
  1. Continuo 0.6-1.4  — la primissima versione (curva sigmoide)
  2. Scaglioni assoluti — versione di stamattina (soglie 0-100 fisse, 1.4..0.6)
  3. Percentile 4yr     — versione attuale (produzione: assign_dca_tiers)

Metrica: sat-per-euro vs PIATTO (a parita' di spesa, quanti BTC in piu'/meno per
euro). Positivo = la modulazione ha aiutato; negativo = avresti fatto meglio a
comprare e basta. Per finestra.

Uso:  python3 -m tools.backtest_compare_all
"""
import math
import numpy as np
import pandas as pd

from src.composite import assign_dca_tiers

HISTORY = "data/composite_history.csv"
PRICES = "data/cache/cryptocompare_btc_daily.csv"

WINDOWS = [
    ("Storia completa 2015->", "2015-01-01"),
    ("Ultimo ciclo 2022->",    "2022-01-01"),
    ("Post-ETF 2024-> (oggi)", "2024-01-01"),
]


def m_continuo(s, mn=0.6, mx=1.4):
    t = 100.0 / (1.0 + math.exp((s - 50) / 10.0))
    c, h = (mn + mx) / 2, (mx - mn) / 2
    return max(mn, min(mx, c + (t / 50 - 1) * h))


def m_assoluto(s):
    if s <= 20: return 1.4
    if s <= 35: return 1.2
    if s < 65:  return 1.0
    if s < 80:  return 0.8
    return 0.6


def spe_adv(price, mult):
    price = np.asarray(price); mult = np.asarray(mult)
    flat = (1.0 / price).sum() / len(price)
    mod = (mult / price).sum() / mult.sum()
    return (mod / flat - 1.0) * 100.0


def main():
    h = pd.read_csv(HISTORY, parse_dates=["date"])
    P = pd.read_csv(PRICES, parse_dates=["date"])[["date", "close"]]
    base = h[["date", "btc_close", "composite_score",
              "target_btc_exposure_pct", "red_count", "green_count"]].copy()
    df = assign_dca_tiers(base).merge(P, on="date").dropna(subset=["close"]).sort_values("date")
    df["m_cont"] = [m_continuo(s) for s in df["composite_score"]]
    df["m_abs"] = [m_assoluto(s) for s in df["composite_score"]]
    # df["dca_multiplier"] = percentile (produzione)

    print("sat-per-euro vs comprare-e-basta (positivo = la modulazione ha aiutato)\n")
    print(f"{'Finestra':<26}{'Continuo':>10}{'Assoluti':>10}{'Percentile':>12}")
    rows = {}
    for wl, ws in WINDOWS:
        b = df[df.date >= ws].set_index("date").resample("W-MON").first().dropna(subset=["close"])
        Pr = b["close"].values
        a1 = spe_adv(Pr, b["m_cont"].values)
        a2 = spe_adv(Pr, b["m_abs"].values)
        a3 = spe_adv(Pr, b["dca_multiplier"].values)
        rows[wl] = (a1, a2, a3)
        print(f"{wl:<26}{a1:>9.1f}%{a2:>9.1f}%{a3:>11.1f}%")

    print("\nRimpianto massimo (la finestra PEGGIORE = quanto puoi restare sotto il piatto):")
    for name, idx in [("Continuo", 0), ("Assoluti", 1), ("Percentile", 2)]:
        worst = min(v[idx] for v in rows.values())
        print(f"  {name:<12} {worst:+.1f}%")

    print("\nModulazione media |mult-1| post-ETF (quanto lo strumento fa DAVVERO qualcosa):")
    b = df[df.date >= "2024-01-01"].set_index("date").resample("W-MON").first().dropna(subset=["close"])
    for name, col in [("Continuo", "m_cont"), ("Assoluti", "m_abs"), ("Percentile", "dca_multiplier")]:
        print(f"  {name:<12} {np.abs(b[col].values - 1).mean():.3f}x")


if __name__ == "__main__":
    main()
