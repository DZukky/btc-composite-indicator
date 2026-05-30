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

# --- Fasce DCA a PERCENTILE MOBILE (walk-forward) -------------------------
# PERCHÉ il cambio (redesign 2026-05-30, validato da second opinion): con soglie
# ASSOLUTE 0-100 il moltiplicatore, post-ETF, restava inchiodato a 1.0× perché lo
# score si comprime nella fascia centrale (mai sopra 75, quasi mai sotto 20). Fix
# adottato anche da Glassnode su MVRV (gen 2025): mappare il RANGO dello score nella
# storia recente, non il livello grezzo. Così lo strumento modula anche quando lo
# score grezzo non esce dalla fascia centrale.
#
# Le 5 fasce riusano le stesse 5 chiavi-segnale → SIGNAL_DETAIL/etichette in
# reporter restano valide (ACCUMULO AGGRESSIVO / INCREMENTALE / STANDARD / RIDOTTO
# / MINIMO). Il `signal` mostrato diventa la FASCIA (azione); lo score 0-100 resta
# il numero di contesto.
#
# AGGRESSIVITÀ dolce 0.5–1.5 (la ricerca sconsiglia di allargare: ~2% di edge in
# più nel raro crollo a fronte del doppio del danno nei tori). Ritarabile qui.
DCA_TIER_MULT = {
    "STRONG_BUY":  1.5,   # ACCUMULO AGGRESSIVO
    "ACCUMULATE":  1.25,  # ACCUMULO INCREMENTALE
    "HOLD":        1.0,   # ACCUMULO STANDARD
    "DERISK":      0.75,  # RIDOTTO
    "STRONG_SELL": 0.5,   # MINIMO
}
# Ordine fascia da "compra di meno" a "compra di più" (per l'overlay di regime).
DCA_TIER_LADDER = ["STRONG_SELL", "DERISK", "HOLD", "ACCUMULATE", "STRONG_BUY"]

DCA_PCT_WINDOW = 1460        # finestra percentile: 4 anni (~1 ciclo halving); espandente finché < win
DCA_TIER_DWELL_DAYS = 21     # permanenza minima in una fascia prima di poter cambiare (stabilità)
DCA_REGIME_OVERLAY = False   # overlay 200gg DISATTIVATO: il backtest A/B mostra che PEGGIORA ogni metrica
                             # (drag −5.9% vs −4.1%, crollo +7.0% vs +8.1%): la 200gg è troppo veloce, in
                             # un toro BTC va spesso sotto durante correzioni sane → compra di più prima del
                             # rialzo. Conferma il warning della ricerca (regime su 3 cicli = overfitting).
                             # Lasciato come flag: rimetti True per riattivarlo.
DCA_SMA_REGIME_DAYS = 200
# Soglie percentile (0-100) per le 5 fasce; gli estremi hanno un hybrid gate
# (percentile estremo AND conferma assoluta) per non inventare segnali nei piatti.
DCA_PCT_AGGR = 10            # ≤10° pct → AGGRESSIVO   (gate: composite ≤35 e ≥4 indicatori verdi)
DCA_PCT_INCR = 30            # ≤30° pct → INCREMENTALE
DCA_PCT_RID = 70            # ≥70° pct → RIDOTTO
DCA_PCT_MIN = 90            # ≥90° pct → MINIMO       (gate: composite ≥65)

# Riapertura del Caffè quotidiano su Telegram: muto fino a questa data (incl. ponte
# 2 giugno 2026), poi i messaggi giornalieri automatici ripartono. Metti None per
# nessun blocco (invia sempre), o sposta la data per ritardare ancora.
TELEGRAM_RESUME_DATE = "2026-06-03"

EMAIL_TO = "info@ghostly.biz"
EMAIL_FROM = "btc-tool@resend.dev"
EMAIL_SUBJECT_PREFIX = "[BTC Composite]"
