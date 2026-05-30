"""Validazione walk-forward del redesign a PERCENTILI vs scaglioni assoluti.

USA LE STESSE FUNZIONI DI PRODUZIONE (src.composite.assign_dca_tiers) → ciò che il
backtest misura è esattamente ciò che la dashboard calcola: nessuna divergenza.

Confronto tre strategie sullo stesso storico:
  A. Piatto          — compra sempre la stessa cifra (baseline)
  B. Assoluto 5-fasce — moltiplicatore dalle soglie assolute (1.4..0.6, vecchio)
  C. Percentile 4yr   — produzione attuale (assign_dca_tiers: percentile mobile +
                        hybrid gate + overlay 200gg + permanenza minima)

Metriche per finestra:
  - sat/euro vs piatto (efficienza)
  - max regret = caso peggiore vs piatto (il 'premio assicurativo' nei tori)
  - modulazione media |mult-1| (quanto lo strumento si muove davvero)

Uso:  python3 -m tools.backtest_percentile
"""
import numpy as np
import pandas as pd

from src.composite import assign_dca_tiers

HISTORY = "data/composite_history.csv"
PRICES = "data/cache/cryptocompare_btc_daily.csv"

WINDOWS = [
    ("Storia completa 2015->", "2015-01-01"),
    ("Ultimo ciclo 2022->",    "2022-01-01"),
    ("Post-ETF 2024->",        "2024-01-01"),
]


def mult_absolute(s: float) -> float:
    if s <= 20:  return 1.4
    if s <= 35:  return 1.2
    if s < 65:   return 1.0
    if s < 80:   return 0.8
    return 0.6


def load() -> pd.DataFrame:
    h = pd.read_csv(HISTORY, parse_dates=["date"])
    p = pd.read_csv(PRICES, parse_dates=["date"])[["date", "close"]]
    # ricostruisco la base e ri-assegno le fasce con le funzioni di PRODUZIONE
    base = h[["date", "btc_close", "composite_score",
              "target_btc_exposure_pct", "red_count", "green_count"]].copy()
    tiered = assign_dca_tiers(base)
    tiered = tiered.merge(p, on="date", how="inner").dropna(subset=["close"]).sort_values("date")
    tiered["m_abs"] = [mult_absolute(s) for s in tiered["composite_score"]]
    return tiered.reset_index(drop=True)


def sat_per_eur_adv(price, mult) -> float:
    price = np.asarray(price); mult = np.asarray(mult)
    flat = (1.0 / price).sum() / len(price)
    mod = (mult / price).sum() / mult.sum()
    return (mod / flat - 1.0) * 100.0


def main():
    df = load()
    print(f"Dati: {df.date.min().date()} -> {df.date.max().date()} ({len(df)} gg)")
    print("Strategie: B=assoluto(1.4..0.6)  C=percentile 4yr (produzione)\n")
    for wlabel, wstart in WINDOWS:
        sub = df[df.date >= wstart]
        buys = sub.set_index("date").resample("W-MON").first().dropna(subset=["close"])
        P = buys["close"].values
        adv_b = sat_per_eur_adv(P, buys["m_abs"].values)
        adv_c = sat_per_eur_adv(P, buys["dca_multiplier"].values)
        mod_b = np.abs(buys["m_abs"].values - 1.0).mean()
        mod_c = np.abs(buys["dca_multiplier"].values - 1.0).mean()
        print(f"=== {wlabel} ({buys.index.min().date()}->{buys.index.max().date()}) ===")
        print(f"  sat/euro vs piatto:  B(assoluto) {adv_b:+5.1f}%   |  C(percentile) {adv_c:+5.1f}%")
        print(f"  modulazione media:   B {mod_b:.2f}x          |  C {mod_c:.2f}x")
        vc = pd.Series(buys["dca_multiplier"].values).value_counts(normalize=True).sort_index()
        print(f"  fasce percentile C:  " + " ".join(f"{k}x:{v*100:.0f}%" for k, v in vc.items()) + "\n")

    # quante volte cambia fascia (stabilità) sull'intero storico
    chg = int((df["signal"] != df["signal"].shift()).sum() - 1)
    yrs = (df.date.max() - df.date.min()).days / 365.25
    print(f"Stabilita': la fascia cambia {chg} volte in {yrs:.1f} anni (~{chg/yrs:.1f}/anno).")


if __name__ == "__main__":
    main()
