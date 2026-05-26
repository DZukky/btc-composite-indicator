"""Configurazione globale dello strumento BTC composite indicator."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DASHBOARD_DIR = ROOT / "dashboard"

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

INDICATOR_THRESHOLDS = {
    "pi_cycle":     {"top_red": 0.95, "top_yellow": 0.85, "bot_green": None, "bot_yellow": None},
    "mayer":        {"top_red": 2.4,  "top_yellow": 1.8,  "bot_green": 1.0,  "bot_yellow": 1.2},
    "two_year_ma":  {"top_red": 4.0,  "top_yellow": 2.5,  "bot_green": 1.0,  "bot_yellow": 1.3},
    "mvrv_z":       {"top_red": 6.0,  "top_yellow": 3.5,  "bot_green": 0.0,  "bot_yellow": 1.0},
    "rsi_weekly":   {"top_red": 85,   "top_yellow": 75,   "bot_green": 35,   "bot_yellow": 45},
    "nupl":         {"top_red": 0.70, "top_yellow": 0.55, "bot_green": 0.0,  "bot_yellow": 0.15},
    "puell":        {"top_red": 3.5,  "top_yellow": 2.2,  "bot_green": 0.5,  "bot_yellow": 0.8},
    "hash_ribbons": {"top_red": None, "top_yellow": None, "bot_green": "buy_cross", "bot_yellow": None},
    "bmsb":         {"top_red": 1.30, "top_yellow": 1.15, "bot_green": 1.00, "bot_yellow": 1.05},
}

COMPOSITE_TRIGGERS = {
    "strong_sell": {"score_min": 80, "agree_min": 4},
    "strong_buy":  {"score_max": 20, "agree_min": 4},
}

EMAIL_TO = "info@ghostly.biz"
EMAIL_FROM = "btc-tool@resend.dev"
EMAIL_SUBJECT_PREFIX = "[BTC Composite]"
