"""Backtest dell'aggressività del moltiplicatore DCA a flusso.

Confronta DCA modulato (compra `mult×` la cifra base ogni periodo) vs DCA piatto.
Metrica: "sats per euro" = BTC accumulati / euro spesi. È invariante alla valuta
e a quanto versi: misura solo se modulare il timing ti dà più BTC per euro.

  advantage% = sats_per_eur(modulato) / sats_per_eur(piatto) - 1

Il moltiplicatore è ricavato dallo score storico con la STESSA curva di composite.py:
  target_pct = 100 / (1 + exp((score-50)/10))
  mult = center + (target_pct/50 - 1) * half,  clamp[min,max]

Uso:  python3 -m tools.backtest_dca      (da btc-tool/)
"""
import math
import pandas as pd

HISTORY = "data/composite_history.csv"
PRICES = "data/cache/cryptocompare_btc_daily.csv"

# Ladder di aggressività da testare: (etichetta, mult_min, mult_max)
LADDER = [
    ("Dolce 0.6-1.4 (attuale)", 0.6, 1.4),
    ("Media 0.5-1.7",           0.5, 1.7),
    ("Aggressiva 0.4-2.0",      0.4, 2.0),
    ("Estrema 0.3-3.0",         0.3, 3.0),
]

WINDOWS = [
    ("Storia completa 2015->", "2015-01-01"),
    ("Ultimo ciclo 2022->",    "2022-01-01"),
    ("Post-ETF 2024->",        "2024-01-01"),
]

FREQS = [("Mensile", "MS"), ("Settimanale", "W-MON")]


def mult_from_score(score: float, mmin: float, mmax: float) -> float:
    target_pct = 100.0 / (1.0 + math.exp((score - 50.0) / 10.0))
    center = (mmin + mmax) / 2.0
    half = (mmax - mmin) / 2.0
    m = center + (target_pct / 50.0 - 1.0) * half
    return max(mmin, min(mmax, m))


def load() -> pd.DataFrame:
    h = pd.read_csv(HISTORY, parse_dates=["date"])[["date", "composite_score"]]
    p = pd.read_csv(PRICES, parse_dates=["date"])[["date", "close"]]
    df = h.merge(p, on="date", how="inner").dropna().sort_values("date")
    return df.set_index("date")


def backtest(df: pd.DataFrame, freq: str, mmin: float, mmax: float) -> float:
    """Ritorna advantage% della modulazione vs DCA piatto su 'sats per euro'."""
    # Punti di acquisto: primo giorno disponibile di ogni periodo
    buys = df.resample(freq).first().dropna()
    price = buys["close"].values
    mult = [mult_from_score(s, mmin, mmax) for s in buys["composite_score"].values]

    # Piatto: 1 euro/periodo -> sats = sum(1/P), euro = N
    flat_sats = sum(1.0 / p for p in price)
    flat_eur = len(price)
    flat_spe = flat_sats / flat_eur

    # Modulato: mult euro/periodo -> sats = sum(mult/P), euro = sum(mult)
    mod_sats = sum(m / p for m, p in zip(mult, price))
    mod_eur = sum(mult)
    mod_spe = mod_sats / mod_eur

    return (mod_spe / flat_spe - 1.0) * 100.0


def main():
    df = load()
    print(f"Dati: {df.index.min().date()} -> {df.index.max().date()} ({len(df)} giorni)\n")
    for wlabel, wstart in WINDOWS:
        sub = df[df.index >= wstart]
        if len(sub) < 60:
            continue
        print(f"=== {wlabel}  ({sub.index.min().date()} -> {sub.index.max().date()}) ===")
        for flabel, freq in FREQS:
            cells = []
            for label, mmin, mmax in LADDER:
                adv = backtest(sub, freq, mmin, mmax)
                cells.append(f"{label.split()[0]:<10}{adv:+6.1f}%")
            print(f"  {flabel:<12} | " + " | ".join(cells))
        print()


if __name__ == "__main__":
    main()
