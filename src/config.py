"""Configurazione globale dello strumento BTC composite indicator."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DASHBOARD_DIR = ROOT / "docs"

for p in (DATA_DIR, CACHE_DIR, DASHBOARD_DIR):
    p.mkdir(parents=True, exist_ok=True)

INDICATOR_WEIGHTS = {
    "pi_cycle": 0.15,
    "mayer": 0.12,
    "two_year_ma": 0.10,
    "mvrv_z": 0.18,
    "rsi_weekly": 0.10,
    "nupl": 0.10,
    "puell": 0.10,
    "hash_ribbons": 0.08,
    "bmsb": 0.07,
}
assert abs(sum(INDICATOR_WEIGHTS.values()) - 1.0) < 1e-6

# Soglie calibrate sui valori REALI ai bottom/top di ciclo osservati 2018-2022:
#   Mayer bottom 0.51-0.71 · 2YMA bottom 0.41-0.78 · BMSB bottom 0.54-0.75
#   (essere "sotto la media mobile" NON è un bottom di ciclo; lo è esserci MOLTO sotto)
INDICATOR_THRESHOLDS = {
    "pi_cycle":     {"top_red": 0.95, "top_yellow": 0.85, "bot_green": None, "bot_yellow": None},
    "mayer":        {"top_red": 2.4,  "top_yellow": 1.8,  "bot_green": 0.65, "bot_yellow": 0.85},
    "two_year_ma":  {"top_red": 4.0,  "top_yellow": 2.5,  "bot_green": 0.55, "bot_yellow": 0.80},
    "mvrv_z":       {"top_red": 6.0,  "top_yellow": 3.5,  "bot_green": 0.0,  "bot_yellow": 1.0},
    "rsi_weekly":   {"top_red": 85,   "top_yellow": 75,   "bot_green": 35,   "bot_yellow": 45},
    "nupl":         {"top_red": 0.70, "top_yellow": 0.55, "bot_green": 0.0,  "bot_yellow": 0.15},
    "puell":        {"top_red": 3.5,  "top_yellow": 2.2,  "bot_green": 0.5,  "bot_yellow": 0.8},
    "hash_ribbons": {"top_red": None, "top_yellow": None, "bot_green": "buy_cross", "bot_yellow": None},
    "bmsb":         {"top_red": 1.30, "top_yellow": 1.15, "bot_green": 0.70, "bot_yellow": 0.90},
}

COMPOSITE_TRIGGERS = {
    "strong_sell": {"score_min": 80, "agree_min": 4},
    "strong_buy":  {"score_max": 20, "agree_min": 4},
}

# --- DCA a flusso ---------------------------------------------------------
# Il modello è puro accumulo: non si vende mai, si modula solo QUANTO comprare.
# Il composite diventa un moltiplicatore sull'importo di acquisto abituale:
#   composite basso (BTC conveniente) → moltiplicatore > 1 (compra di più)
#   composite alto  (BTC caro)        → moltiplicatore < 1 (compra di meno)
# Curva derivata dalla sigmoide esistente, ma compressa nella fascia [MIN, MAX]
# centrata su 1.0 a composite 50 (scelta "dolce": vicino a 50/100/130-140€).
DCA_BASE_AMOUNT = 100     # cifra base illustrativa (€) per gli esempi in dashboard/Telegram
DCA_MULT_MIN = 0.6        # BTC molto caro → compra ~0,6× la cifra base (e accantona la differenza)
DCA_MULT_MAX = 1.4        # BTC molto conveniente → compra ~1,4× la cifra base
DCA_RESERVE_CAP = 30.0    # tetto al salvadanaio (multipli di cifra base): max "polvere da sparo" realistica

# --- 5 scaglioni fissi (sostituiscono la curva continua) ------------------
# PERCHÉ: un moltiplicatore continuo cambiava di un'inezia ogni giorno
# (1,29 → 1,28 → 1,30): inutilizzabile per chi programma un acquisto ricorrente.
# Ora il moltiplicatore è un valore FERMO per ciascuno dei 5 segnali, e cambia
# SOLO quando il segnale cambia. Il segnale ha già l'isteresi (decide_signal,
# margine 5) → niente sfarfallio al confine delle soglie.
# Le 5 fasce coincidono con i 5 segnali e con le 5 etichette già mostrate in
# dashboard (ACCUMULO AGGRESSIVO / INCREMENTALE / STANDARD / RIDOTTO / MINIMO).
# AGGRESSIVITÀ: i 5 valori sono equidistanti tra DCA_MULT_MIN e DCA_MULT_MAX;
# per renderla più/meno aggressiva basta cambiare quei due numeri sopra.
def _dca_bracket_values(mmin: float, mmax: float, n: int = 5) -> list:
    step = (mmax - mmin) / (n - 1)
    return [round(mmax - i * step, 3) for i in range(n)]  # da "compra di più" a "compra di meno"

DCA_SIGNAL_MULT = dict(zip(
    ["STRONG_BUY", "ACCUMULATE", "HOLD", "DERISK", "STRONG_SELL"],
    _dca_bracket_values(DCA_MULT_MIN, DCA_MULT_MAX),
))  # → {STRONG_BUY:1.4, ACCUMULATE:1.2, HOLD:1.0, DERISK:0.8, STRONG_SELL:0.6}

EMAIL_TO = "info@ghostly.biz"
EMAIL_FROM = "btc-tool@resend.dev"
EMAIL_SUBJECT_PREFIX = "[BTC Composite]"
