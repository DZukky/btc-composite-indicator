"""Dashboard rischio sistemico MSTR/Strategy — pagina SEPARATA (docs/risk.html).

Decoupled dal modello di accumulo: gira nel job giornaliero ma in try/except, se
si rompe il btc-tool non se ne accorge. Due tier di dati:
  - Tier A (AUTO): prezzi BTC/MSTR/STRC (Yahoo) + mNAV + stato dei gauge di prezzo.
  - Tier B (MANUALE): data/risk_facts.json (riserva, holdings, put wall, ecc.),
    aggiornato a mano dai filing SEC.
Se Yahoo non risponde → fallback ai prezzi in risk_facts.json (no-rompere).
"""
import json
import urllib.request
from datetime import date

from .config import DATA_DIR, DASHBOARD_DIR

TEMPLATE = (DATA_DIR.parent / "src" / "risk_template.html")
FACTS = DATA_DIR / "risk_facts.json"
OUT = DASHBOARD_DIR / "risk.html"
PUT_DATE = date(2027, 9, 15)


def _it(x: str) -> str:
    """Punto→virgola per i decimali all'italiana."""
    return x.replace(".", ",")


def _yahoo_price(symbol: str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=20))
    return float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])


def _btc_price() -> float:
    from .fetchers import fetch_btc_price_daily
    df = fetch_btc_price_daily(force=False)
    return float(df.iloc[-1]["close"])


def _badge(cls: str, text: str) -> str:
    return f'<span class="badge {cls}">{text}</span>'


def _gauge_state(value, lo, hi, danger_below, watch_below):
    """Ritorna (lv, fillclass, fill%) per un gauge crescente lo→hi."""
    fill = max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))
    if value <= danger_below:
        return "lv-danger", "f-red", fill
    if value < watch_below:
        return "lv-watch", "f-amber", fill
    return "lv-safe", "f-green", fill


def build_risk_dashboard() -> str:
    facts = json.loads(FACTS.read_text())
    tpl = TEMPLATE.read_text()

    # --- Tier A: prezzi (con fallback se Yahoo è giù) ---
    try:
        mstr = _yahoo_price("MSTR")
    except Exception:
        mstr = float(facts["fallback_mstr"])
    try:
        strc = _yahoo_price("STRC")
    except Exception:
        strc = float(facts["fallback_strc"])
    btc = _btc_price()

    holdings = float(facts["btc_holdings"])
    shares = float(facts["mstr_shares_out"])
    peak = float(facts["btc_peak"])
    mnav = (mstr * shares) / (holdings * btc)

    # --- derivati / stati ---
    btc_pct_peak = (btc - peak) / peak * 100.0
    mnav_class = "v-red" if mnav < 0.85 else ("v-amber" if mnav < 1.0 else "v-green")
    mnav_meta = "sconto sul NAV &middot; volano fermo" if mnav < 1.0 else "premio sul NAV &middot; volano attivo"

    # Trigger 01 — BTC vs $60K (scala 60→90K)
    t01_lv, t01_fc, t01_fill = _gauge_state(btc, 60000, 90000, 60000, 68000)
    t01_margin = btc - 60000
    t01_badge = (_badge("b-danger", "Sotto trigger") if btc <= 60000 else
                 _badge("b-watch", "Vicino") if btc < 68000 else
                 _badge("b-safe", "Margine ampio"))
    t01_note = (f"~${t01_margin/1000:.0f}K di margine sopra il trigger" if t01_margin > 0
                else f"sotto il trigger di ${abs(t01_margin)/1000:.0f}K")

    # Trigger 03 — STRC vs $95 (scala 95→100)
    t03_lv, t03_fc, t03_fill = _gauge_state(strc, 95, 100, 95, 98)
    t03_diff = strc - 95
    t03_badge = (_badge("b-danger", "Sotto trigger") if strc < 95 else
                 _badge("b-watch", "Vicino") if strc < 98 else
                 _badge("b-safe", "OK"))
    t03_note = (_it(f"${t03_diff:.2f} sopra il trigger") if t03_diff > 0
                else _it(f"sotto il trigger di ${abs(t03_diff):.2f}"))

    # Trigger 06 — MSTR vs $183, ma data lontana (2027): resta "lontano", nota informativa
    months = max(0, round((PUT_DATE - date.today()).days / 30.4))
    t06_lv = "lv-safe"
    t06_badge = _badge("b-safe", f"Lontano (~{months} mesi)")
    t06_note = (f"già sotto $183 ma data lontana" if mstr < 183
                else f"${mstr-183:.0f} sopra la soglia $183 &middot; monitorare")

    repl = {
        "AS_OF_AUTO": date.today().isoformat(),
        "AS_OF_MANUAL": facts["as_of_manual"],
        "BTC_PRICE": _it(f"${btc/1000:.1f}K"),
        "BTC_META": f"&minus;{abs(btc_pct_peak):.0f}% dal picco {facts['btc_peak_label']} (~${peak/1000:.0f}K)",
        "MNAV": _it(f"{mnav:.2f}×"),
        "MNAV_CLASS": mnav_class,
        "MNAV_META": mnav_meta,
        "RESERVE": f"{facts['reserve_usd_m']:.0f}",
        "RESERVE_FROM": _it(f"{facts['reserve_from_usd_b']:.2f}"),
        "STRC_PRICE": _it(f"{strc:.2f}"),
        "STRC_CLASS": "v-red" if strc < 95 else "v-amber",
        "STRC_META": "sotto la pari ($100)" if strc < 100 else "sopra la pari ($100)",
        "STRC_COUPON": facts["strc_coupon"],
        "MSTR_PRICE": _it(f"{mstr:.2f}"),
        "T01_LV": t01_lv, "T01_FILLCLASS": t01_fc, "T01_FILL": f"{t01_fill:.0f}",
        "T01_NOW": _it(f"ora ~${btc/1000:.0f}K"), "T01_BADGE": t01_badge, "T01_NOTE": t01_note,
        "T03_LV": t03_lv, "T03_FILLCLASS": t03_fc, "T03_FILL": f"{t03_fill:.0f}",
        "T03_NOW": _it(f"ora ${strc:.2f}"), "T03_BADGE": t03_badge, "T03_NOTE": t03_note,
        "T06_LV": t06_lv, "T06_BADGE": t06_badge, "T06_NOTE": t06_note,
        "BTC_BENCH": "~$" + f"{btc:,.0f}".replace(",", "."),
        "BTC_BENCH_FILL": f"{max(0, min(100, btc/126000*100)):.0f}",
        "COST_BASIS": f"{facts['cost_basis']:,.0f}".replace(",", "."),
    }
    for k, v in repl.items():
        tpl = tpl.replace(f"%%{k}%%", str(v))

    OUT.write_text(tpl)
    return str(OUT)


if __name__ == "__main__":
    print(build_risk_dashboard())
