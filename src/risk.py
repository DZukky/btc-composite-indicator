"""Dashboard rischio sistemico MSTR/Strategy — pagina SEPARATA (docs/risk.html).

Decoupled dal modello di accumulo: gira nel job giornaliero ma in try/except, se
si rompe il btc-tool non se ne accorge. Due tier di dati:
  - Tier A (AUTO): prezzi BTC/MSTR/STRC (Yahoo) + mNAV + stato dei gauge di prezzo.
  - Tier B (MANUALE): data/risk_facts.json (riserva, holdings, put wall, ecc.),
    aggiornato a mano dai filing SEC.
Se Yahoo non risponde → fallback ai prezzi in risk_facts.json (no-rompere).
"""
from __future__ import annotations

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

    # --- Livello di rischio COMPLESSIVO (pill header + riassunto per la home) ---
    rank = {"lv-danger": 2, "lv-watch": 1, "lv-safe": 0}
    # T02 riserva = danger fisso (fatto strutturale), T05 MSCI = watch, T04/T06 = safe
    trig_levels = [t01_lv, "lv-danger", t03_lv, "lv-safe", "lv-watch", t06_lv]
    worst = max(trig_levels, key=lambda x: rank[x])
    n_danger = sum(1 for x in trig_levels if x == "lv-danger")
    if worst == "lv-danger":
        alert_pill, alert_class, level = "RISCHIO ELEVATO", "b-danger", "danger"
    elif worst == "lv-watch":
        alert_pill, alert_class, level = "DA OSSERVARE", "b-watch", "watch"
    else:
        alert_pill, alert_class, level = "SOTTO CONTROLLO", "b-safe", "safe"

    # Titolo sintetico per il banner della home: evidenzia ciò che si MUOVE (prezzi)
    hot = []
    if btc <= 60000:
        hot.append(_it(f"BTC ${btc/1000:.1f}K SOTTO il trigger $60K"))
    elif t01_lv == "lv-watch":
        hot.append(_it(f"BTC ${btc/1000:.1f}K vicino al trigger $60K"))
    if strc < 95:
        hot.append(_it(f"STRC ${strc:.0f} sotto $95"))
    hot.append("riserva $ in esaurimento")
    headline = " · ".join(hot[:3])

    summary = {"level": level, "pill": alert_pill, "pill_class": alert_class,
               "headline": headline, "n_danger": n_danger, "as_of": date.today().isoformat(),
               "btc_zone": t01_lv, "strc_zone": t03_lv, "btc": btc, "strc": strc, "mnav": round(mnav, 3)}
    (DATA_DIR / "risk_summary.json").write_text(json.dumps(summary, ensure_ascii=False))

    repl = {
        "ALERT_PILL": alert_pill,
        "ALERT_PILLCLASS": alert_class,
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
    return summary


# --- Alert Telegram event-driven (solo sui CAMBI di stato, non ogni giorno) ----
ALERT_STATE = DATA_DIR / "risk_alert_state.json"
DASHBOARD_RISK_URL = "https://btc-composite-dzukky.pages.dev/risk"
_ZONE_RANK = {"lv-safe": 0, "lv-watch": 1, "lv-danger": 2}


def _btc_line(prev, cur, summary):
    px = _it(f"${summary['btc']/1000:.1f}K")  # comma SOLO sul decimale di questo numero
    if cur == "lv-danger":
        return f"🚨 <b>BTC è sceso SOTTO $60.000</b> (ora {px}), la soglia 'esistenziale' di Strategy. Sale il rischio di vendite forzate."
    if cur == "lv-watch":
        return f"🟠 <b>BTC vicino al trigger $60.000</b> (ora {px}). Da tenere d'occhio."
    return f"✅ <b>BTC è risalito</b> a {px}, di nuovo a distanza dal trigger $60.000."


def _strc_line(prev, cur, summary):
    px = _it(f"${summary['strc']:.2f}")
    if cur == "lv-danger":
        return f"🟠 <b>STRC sotto $95</b> (ora {px}): possibili aumenti del dividendo di Strategy, costo del capitale in salita."
    return f"✅ <b>STRC è risalito sopra $95</b> (ora {px})."


def maybe_send_risk_alert(summary: dict | None) -> None:
    """Invia un avviso Telegram SOLO quando una soglia monitorata cambia stato.

    Stato in data/risk_alert_state.json (committato → persiste). Primo run: seed
    silenzioso (nessun invio, per non blastare la condizione preesistente).
    Pubblico: RISK_ALERT_CHAT_IDS (default = solo Davide via secret).
    """
    if not summary:
        return
    from . import telegram_bot
    cur = {"btc_zone": summary["btc_zone"], "strc_zone": summary["strc_zone"],
           "overall": summary["level"]}
    if not ALERT_STATE.exists():
        ALERT_STATE.write_text(json.dumps(cur))
        print("[risk-alert] stato iniziale salvato (nessun invio)")
        return
    prev = json.loads(ALERT_STATE.read_text())

    lines = []
    if cur["btc_zone"] != prev.get("btc_zone"):
        lines.append(_btc_line(prev.get("btc_zone"), cur["btc_zone"], summary))
    if cur["strc_zone"] != prev.get("strc_zone"):
        lines.append(_strc_line(prev.get("strc_zone"), cur["strc_zone"], summary))
    if not lines:
        return  # nessun cambio → nessun messaggio

    body = "\n\n".join(lines)
    msg = (f"<b>🛡️ Avviso rischio sistemico · Strategy/MSTR</b>\n\n{body}\n\n"
           f"<i>Questo NON tocca il tuo accumulo BTC: è un monitor del rischio strutturale "
           f"del più grande detentore corporate.</i>\n"
           f"🔍 <a href='{DASHBOARD_RISK_URL}'>Apri il monitor completo</a>")
    if telegram_bot.send_message(msg, ids_env="RISK_ALERT_CHAT_IDS"):
        ALERT_STATE.write_text(json.dumps(cur))
        print(f"[risk-alert] inviato ({len(lines)} cambi)")


if __name__ == "__main__":
    print(build_risk_dashboard())
