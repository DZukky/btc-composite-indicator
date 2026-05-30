"""Genera dashboard HTML statica consumer-friendly + email HTML."""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import DASHBOARD_DIR, INDICATOR_WEIGHTS, DCA_BASE_AMOUNT
from .composite import SIGNAL_DESCRIPTIONS


def _buy_numbers(result: dict):
    """Valori DISPLAY per la quota d'acquisto del giorno (modello a flusso DCA).

    L'arrotondamento è solo sulla presentazione (step 0,1×): riduce la falsa
    precisione e lo sfarfallio quotidiano. Il calcolo della riserva resta a piena
    precisione a monte (composite.py). %, € e × derivano TUTTI dal valore arrotondato,
    così sono sempre coerenti tra loro.

    Ritorna (fattore_display, pct_str, importo_eur, riserva_display):
      - fattore_display: moltiplicatore arrotondato a 0,1× (es. 1.3)
      - pct_str: scostamento dal Capitale Base ("+30%", "−30%", "in linea")
      - importo_eur: esempio in € sul Capitale Base illustrativo (derivato dall'arrotondato)
      - riserva_display: salvadanaio in multipli di Capitale Base, arrotondato a 0,1×
    """
    raw = float(result.get("dca_buy_factor", result.get("dca_multiplier", 1.0)))
    buy = round(raw, 2)  # fasce discrete pulite (0.5/0.75/1.0/1.25/1.5): mostro il valore esatto
    amount = round(DCA_BASE_AMOUNT * buy)
    delta = round((buy - 1.0) * 100)
    pct = f"+{delta}%" if delta > 0 else (f"−{abs(delta)}%" if delta < 0 else "in linea")
    reserve = round(float(result.get("reserve_balance", 0.0)), 1)
    return buy, pct, amount, reserve


SIGNAL_DETAIL = {
    "STRONG_BUY": {
        "emoji": "💚",
        "label": "ACCUMULO AGGRESSIVO",
        "action": "Fase di forte sottovalutazione: le metriche indicano una quotazione ben al di sotto del valore intrinseco stimato. Si consiglia di massimizzare l'intensità di accumulo sul Capitale Base.",
        "rationale": "Storicamente, quando il composite è in questa zona BTC ha registrato rally del 300-700% nei 12-24 mesi successivi (bottom 2018, 2020, 2022).",
        "color":   "#15803d",
        "bg":      "#dcfce7",
        "border":  "#16a34a",
    },
    "ACCUMULATE": {
        "emoji": "🌱",
        "label": "ACCUMULO INCREMENTALE",
        "action": "Fase favorevole all'incremento delle posizioni: le metriche indicano una quotazione inferiore al valore intrinseco stimato. Si consiglia un accumulo frazionato superiore alla quota standard.",
        "rationale": "Diversi indicatori sono in territorio positivo. Incrementare l'accumulo in queste fasi ha pagato storicamente.",
        "color":   "#166534",
        "bg":      "#d1fae5",
        "border":  "#22c55e",
    },
    "HOLD": {
        "emoji": "⚖️",
        "label": "ACCUMULO STANDARD",
        "action": "Quotazione sostanzialmente in linea con il valore intrinseco stimato: si mantiene l'accumulo alla quota standard, senza variazioni d'intensità.",
        "rationale": "Il mercato non è né sopravvalutato né sottovalutato in modo significativo. Accumulo di routine.",
        "color":   "#475569",
        "bg":      "#f1f5f9",
        "border":  "#94a3b8",
    },
    "DERISK": {
        "emoji": "🟠",
        "label": "ACCUMULO RIDOTTO",
        "action": "Quotazione superiore al valore intrinseco stimato: si riduce l'intensità dell'accumulo e si accantona la quota non investita nella riserva di capitale. L'accumulo prosegue, senza liquidazioni.",
        "rationale": "Più indicatori stanno entrando in zona di surriscaldamento: conviene moderare gli ingressi e costituire riserva per le fasi successive.",
        "color":   "#9a3412",
        "bg":      "#ffedd5",
        "border":  "#f97316",
    },
    "STRONG_SELL": {
        "emoji": "🔴",
        "label": "ACCUMULO MINIMO",
        "action": "Fase di forte sopravvalutazione: si porta l'accumulo all'intensità minima e si accantona capitale. Nessuna liquidazione delle posizioni — i ribassi successivi alimenteranno gli ingressi futuri.",
        "rationale": "Quattro o più indicatori sono in zona di top storico. I cicli passati (2017, aprile 2021) hanno avuto cali del 50-85% subito dopo: la riserva costituita ora finanzierà gli accumuli su quei ribassi.",
        "color":   "#991b1b",
        "bg":      "#fee2e2",
        "border":  "#dc2626",
    },
}


# Etichette brevi dei 5 livelli = intensità di accumulo (modello puro accumulo, mai vendere)
SIGNAL_SHORT_IT = {
    "STRONG_BUY":  "Accumulo aggressivo",
    "ACCUMULATE":  "Accumulo incrementale",
    "HOLD":        "Accumulo standard",
    "DERISK":      "Accumulo ridotto",
    "STRONG_SELL": "Accumulo minimo",
}


ZONE_TO_SIMPLE = {
    "red":     ("🔴", "Molto negativo", "#dc2626"),
    "orange":  ("🟠", "Negativo",       "#f97316"),
    "neutral": ("⚪", "Neutro",         "#94a3b8"),
    "lime":    ("🟢", "Positivo",       "#22c55e"),
    "green":   ("🟢", "Molto positivo", "#16a34a"),
    "n/a":     ("❔", "n/d",            "#cbd5e1"),
}


INDICATOR_HUMAN = {
    "pi_cycle":     {"label": "Pi Cycle Top",        "what": "Cattura le fasi di bolla parabolica. Quando le medie mobili corte sorpassano quelle lunghe, top in vista."},
    "mayer":        {"label": "Mayer Multiple",      "what": "Distanza del prezzo dalla media 200 giorni. >2.4 = surriscaldato, <1.0 = saldo."},
    "two_year_ma":  {"label": "Media a 2 anni",      "what": "Confronta il prezzo con la sua media biennale. Sotto la media = bottom storico."},
    "mvrv_z":       {"label": "MVRV Z-Score",        "what": "Profitto medio di tutti i possessori BTC. Estremi positivi = top, negativi = bottom."},
    "rsi_weekly":   {"label": "RSI Settimanale",     "what": "Momentum a medio termine. >85 = ipercomprato (top), <35 = ipervenduto (bottom)."},
    "nupl":         {"label": "NUPL",                "what": "Quanto profitto non realizzato hanno i possessori. >0.75 = euforia, <0 = capitolazione."},
    "puell":        {"label": "Puell Multiple",      "what": "Stress dei miner. <0.5 = miner in difficoltà (bottom), >3.5 = miner in festa (top)."},
    "hash_ribbons": {"label": "Hash Ribbons",        "what": "Salute della rete BTC. Quando i miner si arrendono e poi ripartono, è un bottom signal."},
    "bmsb":         {"label": "Bull Market Band",    "what": "Banda di supporto del trend rialzista. Sopra = bull, sotto = bear."},
}


def _hero_banner(result: dict, prev_buy: float | None = None) -> str:
    """Banner gigante in cima con il signal di oggi in italiano chiaro."""
    detail = SIGNAL_DETAIL.get(result["signal"], SIGNAL_DETAIL["HOLD"])
    btc = f"${result['btc_close']:,.0f}" if result["btc_close"] else "n/a"
    buy, pct, amount, reserve = _buy_numbers(result)

    # Variazione vs ieri (sul valore arrotondato mostrato): dice all'utente se deve agire o no
    chip = "display:inline-block;margin-top:10px;font-size:0.8em;font-weight:700;padding:5px 12px;border-radius:20px;border:1px solid"
    if prev_buy is None or abs(buy - prev_buy) < 0.05:
        var_chip = f'<div style="{chip} #bbf7d0;background:#f0fdf4;color:#15803d">✓ Invariata · nessuna modifica da fare</div>'
    elif buy > prev_buy:
        var_chip = f'<div style="{chip} #86efac;background:#dcfce7;color:#15803d">↑ Aumentata da {prev_buy:g}× · aggiorna il ricorrente</div>'
    else:
        var_chip = f'<div style="{chip} #fed7aa;background:#fff7ed;color:#c2410c">↓ Ridotta da {prev_buy:g}× · aggiorna il ricorrente</div>'

    reserve_line = ""
    if reserve >= 0.05:
        reserve_line = (f'<div style="font-size:0.8em;color:#475569;margin-top:8px;line-height:1.4">'
                        f'💰 Riserva di capitale: <b>{reserve:.1f}×</b> il Capitale Base, da impiegare nelle fasi favorevoli</div>')

    return f"""
<div class="hero" style="background:{detail['bg']};border:2px solid {detail['border']};border-radius:16px;padding:32px;margin-bottom:24px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap">
    <div style="flex:1;min-width:280px">
      <div style="font-size:0.95em;color:{detail['color']};opacity:0.85;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Strategia corrente</div>
      <div style="font-size:2.4em;font-weight:700;color:{detail['color']};line-height:1.1">{detail['emoji']} {detail['label']}</div>
      <div style="font-size:1.15em;color:{detail['color']};margin-top:12px;font-weight:500">{detail['action']}</div>
      <div style="font-size:0.95em;color:#475569;margin-top:10px">{detail['rationale']}</div>
    </div>
    <div class="hero-right" style="text-align:right;min-width:200px">
      <div style="font-size:0.85em;color:{detail['color']};opacity:0.85;text-transform:uppercase;letter-spacing:1px">Quota d'acquisto odierna</div>
      <div class="big-target" style="font-size:3.4em;font-weight:800;color:{detail['color']};line-height:1">{buy:g}×</div>
      {var_chip}
      <div style="font-size:0.8em;color:#475569;margin-top:8px;line-height:1.4">
        il <b>Capitale Base</b> · <b style="color:{detail['color']}">{pct}</b> sulla quota standard<br>
        <span style="font-size:0.95em;color:#0f172a">es. €{DCA_BASE_AMOUNT} → <b>~€{amount}</b> oggi</span>
      </div>
      {reserve_line}
      <div style="margin-top:16px;padding:10px 14px;background:white;border-radius:8px;display:inline-block">
        <div style="font-size:0.8em;color:#64748b">BTC oggi</div>
        <div style="font-size:1.3em;font-weight:600;color:#0f172a">{btc}</div>
      </div>
    </div>
  </div>
</div>
"""


def _thermometer(result: dict) -> str:
    """Barra orizzontale con score 0-100 + label zone semantiche."""
    score = result["composite_score"]
    detail = SIGNAL_DETAIL.get(result["signal"], SIGNAL_DETAIL["HOLD"])
    marker_left = max(0, min(100, score))

    return f"""
<div class="card">
  <h2 style="margin:0 0 8px;font-size:1.1em">📊 ANALISI DEL VALORE RELATIVO</h2>
  <p style="margin:0 0 20px;color:#64748b;font-size:0.95em">Composite score: <b style="color:{detail['color']}">{score:.1f} / 100</b> · più è basso, più è economico</p>
  <div style="position:relative;height:48px;border-radius:8px;overflow:hidden;background:linear-gradient(to right,#16a34a 0%,#22c55e 20%,#94a3b8 35%,#94a3b8 65%,#f97316 80%,#dc2626 100%)">
    <div style="position:absolute;left:{marker_left}%;top:-4px;bottom:-4px;width:4px;background:#0f172a;transform:translateX(-50%);box-shadow:0 0 0 2px white"></div>
    <div style="position:absolute;left:{marker_left}%;top:-28px;transform:translateX(-50%);background:#0f172a;color:white;padding:3px 8px;border-radius:6px;font-size:0.85em;font-weight:600;white-space:nowrap">{score:.0f}</div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:10px;font-size:0.78em;color:#64748b">
    <div style="text-align:center;flex:1"><b style="color:#16a34a">💚 0-20</b><br>Accumulo aggressivo</div>
    <div style="text-align:center;flex:1"><b style="color:#22c55e">🌱 20-35</b><br>Accumulo incrementale</div>
    <div style="text-align:center;flex:1"><b style="color:#475569">⚖️ 35-65</b><br>Accumulo standard</div>
    <div style="text-align:center;flex:1"><b style="color:#f97316">🟠 65-80</b><br>Accumulo ridotto</div>
    <div style="text-align:center;flex:1"><b style="color:#dc2626">🔴 80-100</b><br>Accumulo minimo</div>
  </div>
</div>
"""


def _indicators_table_human(result: dict) -> str:
    GRAD = ("linear-gradient(to right,#16a34a 0%,#22c55e 20%,#94a3b8 35%,"
            "#94a3b8 65%,#f97316 80%,#dc2626 100%)")
    cards = []
    for name in INDICATOR_WEIGHTS:
        info = result["indicators"].get(name, {})
        zone = info.get("zone", "n/a")
        emoji, label_simple, color = ZONE_TO_SIMPLE[zone]
        human = INDICATOR_HUMAN.get(name, {})
        score = info.get("score")

        if score is None:
            meter = ('<div style="height:6px;border-radius:3px;background:#e2e8f0"></div>'
                     '<div style="font-size:0.7em;color:#94a3b8;margin-top:5px">dato non disponibile</div>')
        else:
            pos = max(0.0, min(100.0, float(score)))
            meter = (f'<div style="position:relative;height:6px;border-radius:3px;background:{GRAD}">'
                     f'<div style="position:absolute;left:{pos:.0f}%;top:50%;width:11px;height:11px;border-radius:50%;'
                     f'background:#0f172a;border:2px solid #fff;transform:translate(-50%,-50%);'
                     f'box-shadow:0 0 0 1px rgba(15,23,42,0.2)"></div></div>'
                     '<div style="display:flex;justify-content:space-between;font-size:0.64em;color:#94a3b8;margin-top:4px">'
                     '<span>conveniente</span><span>caro</span></div>')

        cards.append(f"""
<div style="display:flex;flex-direction:column;border:1px solid #e2e8f0;border-left:4px solid {color};border-radius:10px;padding:14px 16px;background:#fff">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:7px">
    <span style="font-weight:700;color:#0f172a">{human.get('label', name)}</span>
    <span style="display:inline-flex;align-items:center;gap:5px;background:{color}20;color:{color};padding:4px 10px;border-radius:20px;font-weight:600;font-size:0.8em;white-space:nowrap">{emoji} {label_simple}</span>
  </div>
  <div style="color:#64748b;font-size:0.82em;line-height:1.45;flex:1;margin-bottom:14px">{human.get('what', '')}</div>
  {meter}
</div>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 8px;font-size:1.1em">🔍 Cosa dicono i 9 indicatori</h2>
  <p style="margin:0 0 4px;color:#64748b;font-size:0.95em">
    <b style="color:#16a34a">{result.get('fav_count', 0)} favorevoli</b> all'acquisto ·
    <b style="color:#dc2626">{result.get('neg_count', 0)} negativi</b> ·
    {result.get('neu_count', 0)} neutri
  </p>
  <p style="margin:0 0 18px;color:#94a3b8;font-size:0.85em">
    Questi 9 indicatori, fusi insieme con il loro peso, producono il <b>Segnale di oggi</b> mostrato in cima alla pagina.
    Il pallino su ogni barra mostra quanto quell'indicatore è oggi vicino al "conveniente" o al "caro".
  </p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px">
    {''.join(cards)}
  </div>
</div>
"""


def _action_box(result: dict) -> str:
    detail = SIGNAL_DETAIL.get(result["signal"], SIGNAL_DETAIL["HOLD"])
    buy, pct, amount, reserve = _buy_numbers(result)

    base = (f"<b>Quota d'acquisto di oggi: ≈ {buy:g}× il Capitale Base</b> "
            f"({pct}; es. €{DCA_BASE_AMOUNT} → <b>~€{amount}</b>). L'accumulo prosegue senza interruzioni; nessuna liquidazione delle posizioni.")
    saved = (f"<b>Riserva di capitale</b>: ≈ {reserve:.1f}× il Capitale Base accantonato, da impiegare nelle fasi di sottovalutazione."
             if reserve >= 0.05 else
             "<b>Riserva di capitale</b>: attualmente nulla — si costituisce nelle fasi in cui la quotazione è elevata e l'accumulo viene ridotto.")

    if result["signal"] == "STRONG_BUY":
        steps = [
            base,
            "<b>Esecuzione</b>: finestra di sottovalutazione marcata. Se disponi di riserva o liquidità dedicata, è la fase indicata per impiegarla nell'accumulo.",
            "<b>Monitoraggio</b>: la strategia resta su questo livello finché 4+ indicatori restano favorevoli. Verrai notificato al cambio di livello.",
        ]
    elif result["signal"] == "ACCUMULATE":
        steps = [
            base,
            "<b>Esecuzione</b>: incrementa l'importo degli acquisti ricorrenti rispetto alla quota standard, in modo frazionato.",
            "<b>Monitoraggio</b>: se il composite scende sotto 20 → 'Accumulo aggressivo' → ulteriore incremento dell'intensità.",
        ]
    elif result["signal"] == "HOLD":
        steps = [
            base,
            "<b>Esecuzione</b>: prosegui l'accumulo alla quota standard, senza variazioni d'intensità.",
            "<b>Monitoraggio</b>: variazioni significative del composite (±15 punti in pochi giorni) richiedono una nuova lettura della dashboard.",
        ]
    elif result["signal"] == "DERISK":
        steps = [
            base,
            saved,
            "<b>Monitoraggio</b>: se il composite supera 80 → 'Accumulo minimo' → ulteriore riduzione dell'intensità.",
        ]
    else:  # STRONG_SELL
        steps = [
            base,
            saved,
            "<b>Razionale</b>: confluenza di segnali di top di ciclo. Si evita ogni liquidazione — i ribassi successivi vengono finanziati dalla riserva costituita ora. Disciplina, non FOMO.",
        ]

    steps_html = "".join(f"<li style='margin-bottom:8px'>{s}</li>" for s in steps)

    return f"""
<div class="card" style="background:{detail['bg']};border-left:4px solid {detail['border']};flex:1;min-width:300px;margin-bottom:0">
  <h2 style="margin:0 0 12px;font-size:1.1em;color:{detail['color']}">✅ PROTOCOLLO OPERATIVO</h2>
  <ol style="margin:0;padding-left:20px;color:#1e293b">{steps_html}</ol>
</div>
"""


CYCLE_ANNOTATIONS_HUMAN = [
    ("2018-12-15", "Bottom bear 2018", "bot"),
    ("2020-03-12", "Crash COVID",       "bot"),
    ("2021-04-14", "Top aprile 2021",   "top"),
    ("2021-11-10", "Top novembre 2021", "top"),
    ("2022-11-21", "Bottom 2022",       "bot"),
    ("2024-03-14", "ATH pre-halving",   "top"),
]


REGIME_DETAIL = {
    "BULL":  {"emoji": "🟢", "label": "BULL MARKET", "color": "#15803d", "bg": "#dcfce7",
              "desc": "Trend rialzista di fondo: il prezzo è sopra la media a 200 settimane, lo spartiacque storico tra bull e bear."},
    "BEAR":  {"emoji": "🔴", "label": "BEAR MARKET", "color": "#991b1b", "bg": "#fee2e2",
              "desc": "Trend ribassista di fondo: il prezzo è sotto la media a 200 settimane, lo spartiacque storico tra bull e bear."},
}


def _regime_banner(result: dict) -> str:
    regime = result.get("regime", "BULL")
    rd = REGIME_DETAIL.get(regime, REGIME_DETAIL["BULL"])
    correction = result.get("regime_correction", False)
    tone = "green" if regime == "BULL" else "red"
    head = f"{rd['emoji']} {rd['label'].title()}" + (" · in correzione" if correction else "")
    body = ("Prezzo sopra la media a 200 settimane." if regime == "BULL"
            else "Prezzo sotto la media a 200 settimane.")
    return _radar_card("Regime di mercato", head, body, tone)


def _divergence_banner(result: dict) -> str:
    div = result.get("last_divergence")
    if div == "bull":
        return _radar_card("Divergenza RSI", "📈 Divergenza rialzista",
                           "Possibile inversione al rialzo (RSI weekly).", "green")
    if div == "bear":
        return _radar_card("Divergenza RSI", "📉 Divergenza ribassista",
                           "Possibile inversione al ribasso (RSI weekly).", "red")
    return _radar_card("Divergenza RSI", "➖ Nessuna divergenza",
                       "Nessun reversal RSI nelle ultime 6 settimane.")


DCA_DETAIL = {
    "SOSTENUTO":  {"emoji": "🟢", "color": "#15803d", "bg": "#dcfce7", "border": "#16a34a",
                   "tag": "Prezzo favorevole"},
    "DI ROUTINE": {"emoji": "🔵", "color": "#1e40af", "bg": "#dbeafe", "border": "#3b82f6",
                   "tag": "Prezzo in linea"},
    "RIDOTTO":    {"emoji": "🟠", "color": "#9a3412", "bg": "#ffedd5", "border": "#f97316",
                   "tag": "Prezzo elevato"},
}


def _dca_and_bot_row(result: dict) -> str:
    """Due colonne affiancate: box Strategia DCA + box Istruzioni Bot DCA."""
    dca = result.get("dca") or {"level": "DI ROUTINE", "reason": "", "bot_state": "ATTIVO", "bot_action": ""}
    d = DCA_DETAIL.get(dca["level"], DCA_DETAIL["DI ROUTINE"])
    sma200d = result.get("sma_200d")
    dist = result.get("dist_200d_pct")
    ref = ""
    if sma200d is not None:
        dist_str = f"{dist:+.1f}%" if dist is not None else "n/a"
        ref = f"""<div style="font-size:0.8em;color:#94a3b8;margin-top:8px">
          Media a 200 giorni: ${sma200d:,.0f} · prezzo a {dist_str}</div>"""

    bot_state = dca.get("bot_state", "ATTIVO")
    state_color = "#16a34a" if bot_state == "ATTIVO" else "#f97316"

    buy, pct, amount, reserve = _buy_numbers(result)
    reserve_html = ""
    if reserve >= 0.05:
        reserve_html = (f'<div style="font-size:0.85em;color:{d["color"]};margin-top:8px;font-weight:600">'
                        f'💰 Riserva di capitale: {reserve:.1f}× il Capitale Base</div>')

    # Parametro operativo REALE per il box bot (sostituisce l'esempio astratto "+10-20%")
    if buy > 1.0:
        bot_param = (f"Imposta l'importo della singola ricorrenza a <b>≈{buy:g}× il Capitale Base</b> "
                     f"({pct}; es. <b>€{amount}</b> con base €{DCA_BASE_AMOUNT}), mantenendo la stessa frequenza. "
                     f"Entità e decisione restano tue.")
    elif buy < 1.0:
        bot_param = (f"Riduci l'importo della singola ricorrenza a <b>≈{buy:g}× il Capitale Base</b> "
                     f"({pct}; es. <b>€{amount}</b> con base €{DCA_BASE_AMOUNT}), stessa frequenza; "
                     f"la quota non investita confluisce nella riserva di capitale. Entità e decisione restano tue.")
    else:
        bot_param = ("Mantieni l'importo della ricorrenza alla <b>quota standard (1,0× il Capitale Base)</b>, "
                     "stessa frequenza. Entità e decisione restano tue.")

    sd = SIGNAL_DETAIL.get(result["signal"], SIGNAL_DETAIL["HOLD"])
    sig_name = SIGNAL_SHORT_IT.get(result["signal"], result["signal"])
    dca_box = f"""
<div class="card" style="background:{d['bg']};border-left:4px solid {d['border']};margin-bottom:0;flex:1;min-width:280px">
  <h2 style="margin:0 0 6px;font-size:1.1em;color:{d['color']}">₿ Strategia di accumulo (DCA)</h2>
  <div style="font-size:1.5em;font-weight:700;color:{sd['color']};margin:4px 0">{sd['emoji']} {sig_name}</div>
  <div style="margin:2px 0 8px"><span style="display:inline-block;white-space:nowrap;font-size:0.78em;font-weight:600;background:{d['border']};color:white;padding:4px 12px;border-radius:12px">{d['tag']}</span></div>
  <div style="color:#475569;font-size:0.92em;line-height:1.5">{dca['reason']}</div>
  <div style="font-size:0.95em;color:#0f172a;margin-top:10px">Quota d'acquisto di oggi: <b>{buy:g}×</b> il Capitale Base · <b>{pct}</b> <span style="color:#94a3b8">(es. €{DCA_BASE_AMOUNT} → ~€{amount})</span></div>
  {reserve_html}
  {ref}
</div>"""

    bot_box = f"""
<div class="card" style="margin-bottom:0;flex:1;min-width:280px;border-left:4px solid #64748b">
  <h2 style="margin:0 0 6px;font-size:1.1em">🤖 PARAMETRI OPERATIVI PER BOT DCA</h2>
  <div style="font-size:0.9em;margin:4px 0">
    Stato bot: <span style="font-weight:700;color:{state_color}">{bot_state}</span>
  </div>
  <div style="color:#475569;font-size:0.92em;line-height:1.5">{bot_param}</div>
  <div style="font-size:0.78em;color:#94a3b8;margin-top:8px">
    Indicazione operativa per il tuo bot (Pionex, Crypto.com, ecc.). Da applicare manualmente — lo strumento non si collega al bot né esegue ordini.
  </div>
</div>"""

    return f"""
<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px">
  {dca_box}
  {bot_box}
</div>"""


NEWS_SENTIMENT = {
    "bull":    ("🟢", "Bullish",  "#16a34a"),
    "bear":    ("🔴", "Bearish",  "#dc2626"),
    "neutral": ("⚪", "Neutrale", "#94a3b8"),
}
NEWS_LABEL_COLOR = {"Bullish": "#15803d", "Bearish": "#991b1b", "Neutrale": "#475569"}


def _fear_greed_widget(fng: dict | None) -> str:
    """Widget Crypto Fear & Greed Index — metafora 'emozione' (faccia), distinta dal termometro."""
    if not fng or not fng.get("available"):
        return ""
    v = fng["value"]
    klass_it = fng["classification_it"]
    if v < 25:
        vcolor, face = "#dc2626", "😱"
    elif v < 45:
        vcolor, face = "#f97316", "😨"
    elif v < 55:
        vcolor, face = "#64748b", "😐"
    elif v < 75:
        vcolor, face = "#22c55e", "🙂"
    else:
        vcolor, face = "#16a34a", "🤑"
    return f"""
<div class="card">
  <h2 style="margin:0 0 14px;font-size:1.1em">Fear &amp; Greed Index <span style="font-weight:400;color:#94a3b8;font-size:0.7em">· emozione della folla</span></h2>
  <div style="display:flex;align-items:center;gap:22px;flex-wrap:wrap">
    <div style="display:flex;align-items:center;gap:16px">
      <div style="font-size:3.4em;line-height:1">{face}</div>
      <div>
        <div style="font-size:1.7em;font-weight:800;color:{vcolor};line-height:1.05">{v}<span style="font-size:0.45em;color:#94a3b8;font-weight:600"> /100</span></div>
        <div style="font-size:1.02em;font-weight:700;color:{vcolor};margin-top:1px">{klass_it}</div>
        <div style="font-size:0.84em;color:#64748b;margin-top:3px">{fng['trend']}</div>
      </div>
    </div>
    <div style="flex:1;min-width:230px;border-left:3px solid #f1f5f9;padding-left:18px;color:#64748b;font-size:0.82em;line-height:1.5">
      <b>Lettura contrarian:</b> la paura estrema ha storicamente coinciso con buone occasioni d'acquisto,
      l'avidità estrema con i top. Contesto esterno, non entra nel composite.
    </div>
  </div>
</div>
"""


def _news_widget(news: dict | None) -> str:
    """Widget '📰 Macro Sentiment & Breaking News'. Graceful se feed non disponibili."""
    from .news import safe

    if not news or not news.get("available"):
        return """
<div class="card">
  <h2 style="margin:0 0 6px;font-size:1.1em">📰 Macro Sentiment &amp; Breaking News</h2>
  <p style="margin:0;color:#94a3b8;font-size:0.92em">Notizie non disponibili al momento (le fonti verranno ricontattate al prossimo aggiornamento).</p>
</div>
"""

    bull = news["bull_pct"]
    neu = news["neutral_pct"]
    bear = news["bear_pct"]
    label = news["label"]
    label_color = NEWS_LABEL_COLOR.get(label, "#475569")

    # sentiment a riga compatta (niente barra: è una metrica indicativa, non va enfatizzata)
    bar = f"""
<div style="font-size:0.9em;color:#475569;margin:2px 0 16px">
  <b style="color:#16a34a">🟢 {bull}%</b> Bullish · <b style="color:#64748b">⚪ {neu}%</b> Neutrale · <b style="color:#dc2626">🔴 {bear}%</b> Bearish
</div>"""

    rows = []
    for it in news["items"]:
        emoji, _, color = NEWS_SENTIMENT.get(it["sentiment"], NEWS_SENTIMENT["neutral"])
        title = safe(it["title"])
        link = safe(it["link"])
        src = safe(it["source"])
        date_str = it["published"].strftime("%d/%m") if it.get("published") else ""
        rows.append(f"""
<a href="{link}" target="_blank" rel="noopener noreferrer" class="news-item"
   style="display:flex;align-items:flex-start;gap:10px;padding:11px 10px;border-top:1px solid #f1f5f9;text-decoration:none;border-radius:6px">
  <span style="font-size:0.95em;flex-shrink:0">{emoji}</span>
  <span style="flex:1;min-width:0">
    <span style="font-size:0.93em;color:#2563eb;font-weight:600">{title} <span style="font-size:0.85em">↗</span></span>
    <span style="display:block;font-size:0.78em;color:#94a3b8;margin-top:2px">{src} · {date_str}</span>
  </span>
  <span style="color:#cbd5e1;flex-shrink:0;font-size:1.1em;align-self:center">›</span>
</a>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 14px;font-size:1.1em">📰 Macro Sentiment &amp; Breaking News</h2>
  <div style="display:flex;gap:24px;flex-wrap:wrap">
    <div style="flex:1;min-width:200px;max-width:300px;border-right:1px solid #f1f5f9;padding-right:18px">
      <div style="font-size:0.82em;color:#475569">Clima delle notizie di oggi</div>
      <div style="font-size:1.8em;font-weight:800;color:{label_color};line-height:1.1;margin:2px 0 1px">{label}</div>
      <div style="font-size:0.8em;color:#94a3b8;margin-bottom:14px">su {news['total']} testate analizzate</div>
      {bar}
      <div style="font-size:0.8em;color:#2563eb;font-weight:700;margin-top:6px">👉 Titoli cliccabili (nuova scheda)</div>
    </div>
    <div style="flex:2.2;min-width:280px">
      {''.join(rows)}
    </div>
  </div>
  <p style="margin:16px 0 0;color:#94a3b8;font-size:0.78em;line-height:1.45;border-top:1px solid #f1f5f9;padding-top:12px">
    ℹ️ Le notizie sono <b>contesto</b>, non un segnale operativo: il sentiment dei titoli è rumoroso e
    <b>non entra nel punteggio composite</b>. Quando una notizia è pubblica, il movimento di prezzo è spesso già avvenuto.
  </p>
</div>
"""


def _external_widget(fng: dict | None, news: dict | None) -> str:
    """Widget unico 'contesto esterno' a 2 colonne: Fear&Greed (sx) + sentiment notizie (dx), senza link."""
    fng_ok = bool(fng and fng.get("available"))
    news_ok = bool(news and news.get("available"))
    if not fng_ok and not news_ok:
        return ""

    if fng_ok:
        v = fng["value"]
        if v < 25:
            vcol, face = "#dc2626", "😱"
        elif v < 45:
            vcol, face = "#f97316", "😨"
        elif v < 55:
            vcol, face = "#64748b", "😐"
        elif v < 75:
            vcol, face = "#22c55e", "🙂"
        else:
            vcol, face = "#16a34a", "🤑"
        left = f"""
      <div style="font-size:0.74em;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8;margin-bottom:14px">Fear &amp; Greed Index · emozione della folla</div>
      <div style="display:flex;align-items:center;gap:14px">
        <div style="font-size:3em;line-height:1">{face}</div>
        <div>
          <div style="font-size:1.6em;font-weight:800;color:{vcol};line-height:1.05">{v}<span style="font-size:0.45em;color:#94a3b8;font-weight:600"> /100</span></div>
          <div style="font-size:1.02em;font-weight:700;color:{vcol}">{fng['classification_it']}</div>
          <div style="font-size:0.82em;color:#64748b;margin-top:3px">{fng['trend']}</div>
        </div>
      </div>
      <p style="margin:16px 0 0;color:#94a3b8;font-size:0.78em;line-height:1.45"><b>Lettura contrarian:</b> la paura estrema ha storicamente coinciso con buone occasioni d'acquisto, l'avidità estrema con i top. Contesto esterno, non entra nel composite.</p>"""
    else:
        left = '<div style="color:#94a3b8;font-size:0.9em">Fear &amp; Greed non disponibile.</div>'

    if news_ok:
        b, n, be = news["bull_pct"], news["neutral_pct"], news["bear_pct"]
        lab = news["label"]
        lc = NEWS_LABEL_COLOR.get(lab, "#475569")
        right = f"""
      <div style="font-size:0.74em;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8;margin-bottom:14px">📰 Macro Sentiment</div>
      <div style="font-size:0.85em;color:#475569">Clima delle notizie di oggi</div>
      <div style="font-size:1.9em;font-weight:800;color:{lc};line-height:1.1;margin:2px 0 1px">{lab}</div>
      <div style="font-size:0.8em;color:#94a3b8;margin-bottom:14px">su {news['total']} testate analizzate</div>
      <div style="font-size:0.9em;color:#475569"><b style="color:#16a34a">🟢 {b}%</b> Bullish · <b style="color:#64748b">⚪ {n}%</b> Neutrale · <b style="color:#dc2626">🔴 {be}%</b> Bearish</div>
      <p style="margin:16px 0 0;color:#94a3b8;font-size:0.78em;line-height:1.45">Indicazione di massima sul tono dei titoli: contesto, non un segnale. Non entra nel composite.</p>"""
    else:
        right = '<div style="color:#94a3b8;font-size:0.9em">Notizie non disponibili al momento.</div>'

    return f"""
<div class="card">
  <div style="display:flex;gap:28px;flex-wrap:wrap">
    <div style="flex:1;min-width:240px">{left}</div>
    <div style="flex:1;min-width:240px;border-left:1px solid #eef2f7;padding-left:28px">{right}</div>
  </div>
</div>
"""


def _history_with_signals(history: pd.DataFrame, divergences: pd.DataFrame | None = None) -> str:
    """Grafico unico: prezzo BTC log con punti scatter colorati ai cambi di signal."""
    if history is None or history.empty:
        return ""

    h = history.copy().sort_values("date").reset_index(drop=True)
    h["signal_prev"] = h["signal"].shift(1)
    changes = h[h["signal"] != h["signal_prev"]].dropna(subset=["signal_prev"])

    # Pannello singolo: solo prezzo BTC + segnali sovrapposti
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=h["date"], y=h["btc_close"], name="BTC", mode="lines",
        line=dict(color="#0f172a", width=1.4),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        showlegend=False,
    ))

    for sig, color, marker in [
        ("STRONG_BUY",  "#16a34a", "triangle-up"),
        ("ACCUMULATE",  "#86efac", "circle"),
        ("DERISK",      "#fb923c", "circle"),
        ("STRONG_SELL", "#dc2626", "triangle-down"),
    ]:
        sub = changes[changes["signal"] == sig]
        if len(sub):
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub["btc_close"], mode="markers", showlegend=False,
                marker=dict(color=color, size=12, symbol=marker,
                            line=dict(color="white", width=1.5)),
                hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<br><b>" + SIGNAL_SHORT_IT.get(sig, sig) + "</b><extra></extra>",
            ))

    # Markers divergenze RSI sul prezzo (piccole X colorate)
    if divergences is not None and not divergences.empty:
        h_idx = h.set_index("date")["btc_close"]
        for dtype, color in [("bull", "#16a34a"), ("bear", "#dc2626")]:
            sub = divergences[divergences["type"] == dtype]
            xs, ys = [], []
            for _, dv in sub.iterrows():
                dd = pd.to_datetime(dv["date"])
                nearest = h_idx.index[h_idx.index.get_indexer([dd], method="nearest")[0]] if len(h_idx) else None
                if nearest is not None:
                    xs.append(nearest)
                    ys.append(h_idx.loc[nearest])
            if xs:
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="markers", showlegend=False,
                    marker=dict(color=color, size=9, symbol="x-thin", line=dict(color=color, width=2)),
                    hovertemplate="%{x|%Y-%m-%d}<br>Divergenza " + dtype + "<extra></extra>",
                ))

    for date_str, label, kind in CYCLE_ANNOTATIONS_HUMAN:
        ts = pd.to_datetime(date_str)
        if ts < h["date"].min() or ts > h["date"].max():
            continue
        col = "#dc2626" if kind == "top" else "#16a34a"
        fig.add_vline(x=ts, line=dict(color=col, width=1, dash="dot"))

    fig.update_yaxes(type="log", title_text="USD (log)")
    fig.update_layout(
        template="plotly_white",
        height=420,
        margin=dict(l=46, r=16, t=10, b=30),
        hovermode="x unified",
        showlegend=False,
        dragmode=False,  # niente pan/zoom col drag → su mobile lo scroll resta alla pagina
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="chart-history",
                       config={"responsive": True, "displayModeBar": False,
                               "scrollZoom": False, "doubleClick": False,
                               "staticPlot": False},
                       default_width="100%")


def _outcome_cell(curr: str, price_at: float, price_after: float | None):
    """Cella esito per un orizzonte. ✅/❌ + % oppure trattino se non maturo."""
    if price_after is None:
        return '<span style="color:#cbd5e1">–</span>'
    if curr == "HOLD":
        return '<span style="color:#94a3b8">—</span>'
    chg = (price_after - price_at) / price_at * 100
    is_buy = curr in ("STRONG_BUY", "ACCUMULATE")
    correct = (chg > 0) if is_buy else (chg < 0)
    color = "#16a34a" if correct else "#dc2626"
    icon = "✅" if correct else "❌"
    return f'<span style="color:{color};font-weight:600;white-space:nowrap">{icon} {chg:+.0f}%</span>'


def _recent_signal_changes(history: pd.DataFrame, n: int = 8, horizons=(30, 90, 180)) -> str:
    if history is None or history.empty:
        return ""
    h = history.copy().sort_values("date").reset_index(drop=True)
    h["signal_prev"] = h["signal"].shift(1)
    price_by_date = h.set_index("date")["btc_close"]
    last_date = h["date"].max()
    min_h = min(horizons)

    # cambi con il più breve orizzonte già maturo (≥30gg) e degli ultimi ~6 mesi
    all_changes = h[h["signal"] != h["signal_prev"]].dropna(subset=["signal_prev"])
    all_changes = all_changes[
        (all_changes["date"] <= last_date - pd.Timedelta(days=min_h)) &
        (all_changes["date"] >= last_date - pd.Timedelta(days=180))
    ]
    changes = all_changes.tail(n).iloc[::-1]
    if not len(changes):
        return ""

    def price_at_horizon(date, days):
        td = date + pd.Timedelta(days=days)
        if td > last_date:
            return None
        idx = price_by_date.index.get_indexer([td], method="nearest")[0]
        return float(price_by_date.iloc[idx])

    rows = []
    for _, r in changes.iterrows():
        curr = r["signal"]
        d_curr = SIGNAL_DETAIL.get(curr, SIGNAL_DETAIL["HOLD"])
        curr_it = SIGNAL_SHORT_IT.get(curr, curr)
        cells = "".join(
            f'<td data-label="Esito {hz}gg" style="padding:10px 12px">{_outcome_cell(curr, float(r["btc_close"]), price_at_horizon(r["date"], hz))}</td>'
            for hz in horizons
        )
        rows.append(f"""<tr>
          <td data-label="Data" style="padding:10px 12px;color:#475569">{r['date'].date()}</td>
          <td data-label="BTC" style="padding:10px 12px;font-family:monospace">${r['btc_close']:,.0f}</td>
          <td data-label="Segnale" style="padding:10px 12px;font-weight:600;color:{d_curr['color']}">{d_curr['emoji']} {curr_it}</td>
          {cells}
        </tr>""")

    esito_headers = "".join(
        f'<th style="padding:8px 12px;text-align:left">Esito {hz}gg</th>' for hz in horizons
    )
    return f"""
<div class="card">
  <h2 style="margin:0 0 6px;font-size:1.1em">📜 Il modello alla prova · ultimi 6 mesi</h2>
  <p style="margin:0 0 12px;color:#64748b;font-size:0.92em">
    Ogni riga è un <b>cambio di livello di accumulo</b> suggerito dal modello. Le colonne <b>Esito</b> mostrano come si è
    mosso il prezzo nei 30/90/180 giorni dopo: ✅ se è andato nella <b>direzione prevista</b>, ❌ se no
    (trattino = orizzonte non ancora maturo). Serve a <b>convalidare la bontà del segnale</b>, non a misurare il rendimento del modello.
    Lo storico completo è il <b>grafico qui sopra</b>.
  </p>
  <div class="tbl-scroll"><table class="changes-tbl" style="width:100%;border-collapse:collapse">
    <thead><tr style="background:#f1f5f9;color:#475569;font-size:0.85em;text-transform:uppercase;letter-spacing:1px">
      <th style="padding:8px 12px;text-align:left">Data</th>
      <th style="padding:8px 12px;text-align:left">BTC</th>
      <th style="padding:8px 12px;text-align:left">Nuova indicazione</th>
      {esito_headers}
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
</div>
"""


def _phase_maturity_alert(history: pd.DataFrame, current_signal: str | None = None) -> str:
    """Alert adattivo (sezione ②): da quanti giorni dura la fase d'accumulo corrente
    rispetto alla sua durata tipica. Diventa un warning ambra SOLO quando la supera;
    altrimenti è una nota di contesto neutra (come '➖ nessuna divergenza')."""
    if history is None or history.empty:
        return ""
    h = history.copy().sort_values("date").reset_index(drop=True)
    current = current_signal or h["signal"].iloc[-1]

    streak = 0
    for s in reversed(h["signal"].tolist()):
        if s == current:
            streak += 1
        else:
            break
    streak = max(1, streak)

    runs = []
    run_sig, run_len = h["signal"].iloc[0], 1
    for s in h["signal"].iloc[1:]:
        if s == run_sig:
            run_len += 1
        else:
            runs.append((run_sig, run_len))
            run_sig, run_len = s, 1
    runs.append((run_sig, run_len))
    same = [ln for sg, ln in runs if sg == current]
    avg_dur = max(1, round(sum(same) / len(same))) if same else streak

    d = SIGNAL_DETAIL.get(current, SIGNAL_DETAIL["HOLD"])
    name = SIGNAL_SHORT_IT.get(current, current)
    if streak > avg_dur:
        return _radar_card("⏱️ Durata della fase", f"⚠️ Fase matura · {streak}gg",
                           f"Oltre la durata tipica (~{avg_dur}gg): possibile cambio.", "amber")
    return _radar_card("⏱️ Durata della fase", f"{d['emoji']} {streak}gg in {name.lower()}",
                       f"Durata tipica ~{avg_dur}gg · nella norma.")


def _signal_distribution(history: pd.DataFrame, current_signal: str | None = None) -> str:
    """Sezione storica ④: barre di frequenza per livello (quanto spesso siamo stati
    a ciascuna intensità) con la durata media tipica di ciascuna fase."""
    if history is None or history.empty:
        return ""
    h = history.copy().sort_values("date").reset_index(drop=True)
    counts = h["signal"].value_counts()
    total = int(counts.sum())
    order = ["STRONG_BUY", "ACCUMULATE", "HOLD", "DERISK", "STRONG_SELL"]

    # Stato corrente (coerente con l'hero): serve solo per evidenziare la barra attuale
    current = current_signal or h["signal"].iloc[-1]

    # Durata media per livello (lunghezza media dei run consecutivi) → "Media Xgg"
    runs = []
    run_sig, run_len = h["signal"].iloc[0], 1
    for s in h["signal"].iloc[1:]:
        if s == run_sig:
            run_len += 1
        else:
            runs.append((run_sig, run_len))
            run_sig, run_len = s, 1
    runs.append((run_sig, run_len))

    # --- Barre di frequenza: durata media per livello + totale storico ----
    avg_by_sig = {}
    for sig in order:
        lens = [ln for s, ln in runs if s == sig]
        avg_by_sig[sig] = round(sum(lens) / len(lens)) if lens else 0

    bars = []
    for sig in order:
        n = int(counts.get(sig, 0))
        pct = 100 * n / total if total else 0
        d = SIGNAL_DETAIL.get(sig, SIGNAL_DETAIL["HOLD"])
        name = SIGNAL_SHORT_IT.get(sig, sig)
        is_cur = sig == current
        name_style = f"color:{d['color']};font-weight:700" if is_cur else f"color:{d['color']};font-weight:600"
        outline = f";box-shadow:inset 0 0 0 2px {d['border']}" if is_cur else ""
        avg_sig = avg_by_sig.get(sig, 0)
        media_label = (f'<span style="position:absolute;left:calc({pct:.1f}% + 10px);top:50%;transform:translateY(-50%);'
                       f'font-size:0.74em;font-weight:600;color:#475569;white-space:nowrap">Media {avg_sig}gg</span>')
        bars.append(f"""
<div style="margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;font-size:0.88em;margin-bottom:6px;gap:10px">
    <span style="{name_style}">{d['emoji']} {name}</span>
    <span style="color:#64748b;white-space:nowrap">Totale storico in questa fase <b>{n} giorni</b> · {pct:.1f}%</span>
  </div>
  <div style="position:relative;height:22px;background:#f1f5f9;border-radius:7px{outline}">
    <div style="position:absolute;left:0;top:0;bottom:0;width:{pct:.1f}%;background:{d['border']};border-radius:7px"></div>
    {media_label}
  </div>
</div>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 8px;font-size:1.1em">📊 Distribuzione storica dell'accumulo</h2>
  <p style="margin:0 0 16px;color:#64748b;font-size:0.92em">
    <b>Quanto è frequente ogni intensità</b>, sugli ultimi {total} giorni (dal {h['date'].min().date()}).
    L'<b>Accumulo standard</b> è la norma; gli estremi (aggressivo/minimo) sono <b>rari</b> — per questo contano quando compaiono.
  </p>
  {''.join(bars)}
</div>
"""


def _explain_target(result: dict) -> str:
    buy, pct, amount, reserve = _buy_numbers(result)
    return f"""
<div class="card" style="background:#eff6ff;border-left:4px solid #3b82f6;flex:1;min-width:300px;margin-bottom:0">
  <h2 style="margin:0 0 8px;font-size:1em;color:#1e40af">ℹ️ NOTE SULLA MODULAZIONE DEL CAPITALE</h2>
  <p style="margin:0;color:#1e3a8a;font-size:0.92em;line-height:1.55">
    Il riferimento è il <b>Capitale Base</b>: la quota d'acquisto standard che destini periodicamente a BTC
    (es. €{DCA_BASE_AMOUNT} — parametro personale).<br><br>
    Il valore <b>{buy:g}×</b> ({pct}) è il <b>fattore di modulazione</b> applicato al Capitale Base: oggi indica un impiego
    {('superiore' if buy > 1 else 'inferiore' if buy < 1 else 'pari')} alla quota standard
    (es. €{DCA_BASE_AMOUNT} → ~€{amount}). Nelle fasi di sopravvalutazione l'intensità si riduce e la quota non investita
    confluisce nella <b>riserva di capitale</b>; nelle fasi di sottovalutazione l'intensità aumenta, attingendo alla riserva.
    <b>Nessuna liquidazione</b>: si modula esclusivamente l'intensità di accumulo.
  </p>
</div>
"""


def _chart_legend() -> str:
    """Legenda HTML custom, simboli coerenti al 100% con i marker del grafico,
    divisa in due categorie."""
    def it(symbol, color, label):
        return (f'<span style="display:inline-flex;align-items:center;gap:5px;white-space:nowrap">'
                f'<span style="color:{color};font-size:1.05em;line-height:1">{symbol}</span>'
                f'<span style="color:#475569;font-size:0.85em">{label}</span></span>')

    tendenza = " &nbsp;·&nbsp; ".join([
        it("▲", "#16a34a", "Accumulo aggressivo"),
        it("●", "#4ade80", "Accumulo incrementale"),
        it("●", "#fb923c", "Accumulo ridotto"),
        it("▼", "#dc2626", "Accumulo minimo"),
    ])
    momento = " &nbsp;·&nbsp; ".join([
        it("✕", "#16a34a", "Div. rialzista"),
        it("✕", "#dc2626", "Div. ribassista"),
    ])

    def dash(color, label):
        return (f'<span style="display:inline-flex;align-items:center;gap:6px;white-space:nowrap">'
                f'<span style="display:inline-block;width:0;height:15px;border-left:2px dashed {color}"></span>'
                f'<span style="color:#475569;font-size:0.85em">{label}</span></span>')

    cicli = " &nbsp;·&nbsp; ".join([
        dash("#dc2626", "Top di ciclo storico"),
        dash("#16a34a", "Bottom di ciclo storico"),
    ])
    return f"""
<div style="margin-top:8px;border-top:1px solid #f1f5f9;padding-top:12px">
  <div style="font-size:0.72em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:6px">Segnali di tendenza</div>
  <div style="display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:12px">{tendenza}</div>
  <div style="font-size:0.72em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:6px">Indicatori di momento</div>
  <div style="display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:12px">{momento}</div>
  <div style="font-size:0.72em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:6px">Linee verticali tratteggiate</div>
  <div style="display:flex;flex-wrap:wrap;gap:6px 14px">{cicli}</div>
</div>"""


def _section_header(num: str, title: str) -> str:
    return f"""
<div style="margin:36px 0 16px">
  <div style="font-size:1.2em;font-weight:700;color:#0f172a">{num}&nbsp;&nbsp;{title}</div>
  <div style="height:2px;background:linear-gradient(to right,#94a3b8,#e2e8f0 60%,transparent);margin-top:8px"></div>
</div>"""


def _radar_card(label, head, body, tone="neutral") -> str:
    """Card compatta del radar di contesto (③). Neutro = muto/grigio (recede);
    tone colorato solo quando il segnale è attivo (risalta)."""
    palette = {
        "neutral": ("#e2e8f0", "#475569", "#ffffff"),
        "green":   ("#16a34a", "#15803d", "#f0fdf4"),
        "red":     ("#dc2626", "#991b1b", "#fef2f2"),
        "amber":   ("#ca8a04", "#92400e", "#fffbeb"),
    }
    accent, headcol, bg = palette.get(tone, palette["neutral"])
    return f"""<div style="border:1px solid #e8edf3;border-left:3px solid {accent};border-radius:8px;padding:11px 14px;background:{bg}">
  <div style="font-size:0.66em;text-transform:uppercase;letter-spacing:0.5px;color:#94a3b8">{label}</div>
  <div style="font-size:0.98em;font-weight:700;color:{headcol};margin:3px 0 2px">{head}</div>
  <div style="font-size:0.78em;color:#64748b;line-height:1.4">{body}</div>
</div>"""


def _golden_death_alert(ind_df: pd.DataFrame, window_days: int = 180, confirm_days: int = 21) -> str:
    """Golden/Death Cross (SMA 50 vs 200 daily) — variante DCA con conferma anti-whipsaw."""
    if ind_df is None or ind_df.empty or "dma_200" not in ind_df:
        return ""
    df = ind_df.dropna(subset=["dma_200"]).reset_index(drop=True)
    df = df.assign(dma_50=df["close"].rolling(50).mean()).dropna(subset=["dma_50"]).reset_index(drop=True)
    if len(df) < 2:
        return ""
    above = (df["dma_50"] > df["dma_200"]).tolist()
    dates = pd.to_datetime(df["date"])
    last_date = dates.iloc[-1]
    above_now = above[-1]

    # incroci grezzi → tieni solo quelli "confermati" (lo stato regge ≥ confirm_days)
    raw = [(i, "golden" if above[i] else "death") for i in range(1, len(above)) if above[i] != above[i - 1]]
    confirmed = []
    for k, (i, t) in enumerate(raw):
        end_i = raw[k + 1][0] if k + 1 < len(raw) else len(df) - 1
        if (dates.iloc[end_i] - dates.iloc[i]).days >= confirm_days:
            confirmed.append((i, t))

    if confirmed:
        ci, ct = confirmed[-1]
        age = int((last_date - dates.iloc[ci]).days)
        if age <= window_days and ct == "golden":
            return _radar_card("Golden / Death Cross", f"📈 Golden Cross · {age}gg fa",
                "Medie 50/200gg: trend di fondo tornato rialzista.", "green")
        if age <= window_days and ct == "death":
            return _radar_card("Golden / Death Cross", f"📉 Death Cross · {age}gg fa",
                "Medie 50/200gg: trend di fondo in territorio debole.", "red")
        trend = "rialzista" if ct == "golden" else "ribassista"
        return _radar_card("Golden / Death Cross", "➖ Nessun incrocio recente",
            f"Trend di fondo {trend} (medie 50/200gg).")
    trend = "rialzista" if above_now else "ribassista"
    return _radar_card("Golden / Death Cross", "➖ Nessun incrocio recente",
        f"Trend di fondo {trend} (medie 50/200gg).")


def _pi_cycle_alert(ind_df: pd.DataFrame, window_days: int = 180) -> str:
    """Pi Cycle Top: 111DMA che supera 2×350DMA → top di ciclo storico (indicatore standard)."""
    if ind_df is None or "pi_cycle" not in ind_df:
        return ""
    df = ind_df.dropna(subset=["pi_cycle"]).reset_index(drop=True)
    if len(df) < 2:
        return ""
    last_date = pd.to_datetime(df["date"].iloc[-1])
    r = float(df["pi_cycle"].iloc[-1])
    cross_i = None
    for i in range(len(df) - 1, 0, -1):
        if df["pi_cycle"].iloc[i] >= 1.0 and df["pi_cycle"].iloc[i - 1] < 1.0:
            cross_i = i
            break
    age = int((last_date - pd.to_datetime(df["date"].iloc[cross_i])).days) if cross_i is not None else None
    pct = max(0, round(r * 100))
    if age is not None and age <= window_days:
        return _radar_card("Pi Cycle Top", f"⚠️ Top di ciclo scattato · {age}gg fa",
            "Storico indicatore dei massimi di ciclo. Frena gli acquisti.", "red")
    if r >= 0.9:
        return _radar_card("Pi Cycle Top", f"🟡 Vicino al top · {pct}%",
            "Si avvicina al trigger di top di ciclo.", "amber")
    return _radar_card("Pi Cycle Top", "➖ Nessun top segnalato",
        "Lontano dalla soglia di top di ciclo.")


def _hash_ribbons_alert(ind_df: pd.DataFrame, window_days: int = 180,
                        capit_days: int = 14, dedup_days: int = 90) -> str:
    """Hash Ribbons — variante DCA stretta: solo dopo vera capitolazione + de-dup."""
    if ind_df is None or "hash_ribbons" not in ind_df:
        return ""
    df = ind_df.dropna(subset=["hash_ribbons"]).reset_index(drop=True)
    if len(df) < 2:
        return ""
    ratio_s = df["hash_ribbons"].tolist()
    dates = pd.to_datetime(df["date"])
    last_date = dates.iloc[-1]
    ratio_now = float(ratio_s[-1])

    # capitolazione = ratio<1 per ≥ capit_days consecutivi, POI ripartenza (cross sopra 1)
    valid_buys = []
    last_kept = None
    cap_run = 0
    for i in range(len(df)):
        if ratio_s[i] < 1.0:
            cap_run += 1
        else:
            if cap_run >= capit_days and i > 0 and ratio_s[i - 1] < 1.0:  # ripartenza dopo vera capitolazione
                if last_kept is None or (dates.iloc[i] - dates.iloc[last_kept]).days >= dedup_days:
                    valid_buys.append(i)
                    last_kept = i
            cap_run = 0

    age = int((last_date - dates.iloc[valid_buys[-1]]).days) if valid_buys else None
    if age is not None and age <= window_days:
        return _radar_card("Hash Ribbons (miner)", f"🟢 Segnale d'acquisto · {age}gg fa",
            "Ripartenza miner dopo capitolazione: zona di accumulo.", "green")
    if ratio_now < 1.0:
        return _radar_card("Hash Ribbons (miner)", "🟠 Miner in capitolazione",
            "Miner sotto stress: spesso precede un bottom.", "amber")
    return _radar_card("Hash Ribbons (miner)", "➖ Nessun segnale recente",
        "Rete miner in salute.")


def build_dashboard(result: dict, ind_df: pd.DataFrame, history: pd.DataFrame | None = None,
                    divergences: pd.DataFrame | None = None, news: dict | None = None,
                    fng: dict | None = None) -> Path:
    prev_buy = None
    if history is not None and "dca_buy_factor" in history.columns and len(history) >= 2:
        try:
            prev_buy = round(float(history["dca_buy_factor"].iloc[-2]), 2)
        except Exception:
            prev_buy = None
    hero = _hero_banner(result, prev_buy=prev_buy)
    regime_banner = _regime_banner(result)
    divergence_banner = _divergence_banner(result)
    maturity_alert = _phase_maturity_alert(history, result.get("signal")) if history is not None else ""
    golden_death = _golden_death_alert(ind_df)
    pi_cycle_alert = _pi_cycle_alert(ind_df)
    hash_alert = _hash_ribbons_alert(ind_df)
    dca = _dca_and_bot_row(result)
    therm = _thermometer(result)
    indicators = _indicators_table_human(result)
    external_widget = _external_widget(fng, news)
    history_chart = _history_with_signals(history, divergences=divergences) if history is not None else ""
    # Tabella "Il modello alla prova" DISATTIVATA (scelta Davide 2026-05-30): il test
    # direzionale ✅/❌ giudica un modello di ACCUMULO come se predicesse il prezzo a
    # 30/90gg — frame sbagliato (la validazione vera è il backtest sui cicli). La
    # funzione _recent_signal_changes() è conservata: per riattivarla, ripristina la
    # riga sotto a `_recent_signal_changes(history) if history is not None else ""`.
    changes_table = ""

    btc_price = result["btc_close"]
    btc_price_str = f"${btc_price:,.0f}" if btc_price else "n/a"
    _mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
             "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    try:
        _y, _m, _d = str(result["date"]).split("-")
        date_it = f"{int(_d)} {_mesi[int(_m) - 1]} {_y}"
    except Exception:
        date_it = str(result["date"])

    html = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BTC Composite — {result['date']}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f8fafc; color: #0f172a; margin: 0; padding: 24px 16px;
         overflow-x: hidden; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px; font-size: 1.5em; letter-spacing: -0.01em; }}
  .tagline {{ color: #334155; font-size: 1.02em; margin-bottom: 6px; }}
  .meta {{ color: #94a3b8; margin-bottom: 24px; font-size: 0.9em; }}
  .card {{ background: white; border-radius: 12px; padding: 24px;
           box-shadow: 0 1px 4px rgba(15,23,42,0.08); margin-bottom: 20px; }}
  .news-item {{ transition: background 0.12s ease; }}
  .news-item:hover {{ background: #f1f5f9; }}
  table {{ font-size: 0.95em; width: 100%; }}
  .tbl-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  .js-plotly-plot, .plotly, .plot-container {{ width: 100% !important; max-width: 100%; }}
  /* su touch lo scroll verticale resta alla pagina, niente pan/zoom accidentale del grafico */
  #chart-history, #chart-history *, .js-plotly-plot, .js-plotly-plot * {{ touch-action: pan-y !important; }}
  .disclaimer {{ background: #fef9e7; border-left: 4px solid #f1c40f;
                 padding: 14px 18px; border-radius: 4px; margin: 24px 0 8px;
                 color: #713f12; font-size: 0.88em; line-height: 1.5; }}
  /* ---- Mobile ---- */
  @media (max-width: 640px) {{
    body {{ padding: 14px 10px; }}
    h1 {{ font-size: 1.25em; }}
    .tagline {{ font-size: 0.95em; }}
    .card {{ padding: 16px; margin-bottom: 14px; border-radius: 10px; }}
    .hero {{ padding: 20px !important; }}
    .hero .big-target {{ font-size: 2.4em !important; }}
    /* il blocco 'esposizione' dell'hero torna a sinistra e a tutta larghezza */
    .hero-right {{ text-align: left !important; min-width: 100% !important; margin-top: 12px; }}
    table {{ font-size: 0.85em; }}
    th, td {{ padding: 8px 8px !important; }}
    /* Tabella cambi → schede impilate: niente scroll orizzontale, tutto visibile */
    .changes-tbl thead {{ display: none; }}
    .changes-tbl, .changes-tbl tbody, .changes-tbl tr, .changes-tbl td {{ display: block; width: 100%; }}
    .changes-tbl tr {{ border: 1px solid #e2e8f0; border-radius: 10px; padding: 6px 12px; margin-bottom: 12px; }}
    .changes-tbl td {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 6px 0 !important; border-bottom: 1px solid #f1f5f9;
    }}
    .changes-tbl td:last-child {{ border-bottom: none; }}
    .changes-tbl td::before {{
      content: attr(data-label); color: #94a3b8; font-weight: 600;
      font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; margin-right: 12px;
    }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
    BTC Composite Model
    <span style="font-size:0.5em;font-weight:700;letter-spacing:1px;background:#e0e7ff;color:#4338ca;padding:3px 9px;border-radius:6px;vertical-align:middle">BETA</span>
    <span style="font-size:0.5em;font-weight:700;letter-spacing:1px;background:#dcfce7;color:#15803d;padding:3px 9px;border-radius:6px;vertical-align:middle">DCA</span>
  </h1>
  <div class="tagline">Modello di valutazione ciclica per l'accumulo frazionato di Bitcoin.</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:10px 0 26px">
    <span style="display:inline-flex;align-items:center;gap:6px;background:#f1f5f9;color:#475569;font-size:0.85em;font-weight:600;padding:6px 13px;border-radius:20px">🗓️ Aggiornato il {date_it}</span>
    <span style="display:inline-flex;align-items:center;gap:6px;background:#fff7ed;color:#ea580c;font-size:0.95em;font-weight:800;padding:6px 14px;border-radius:20px;border:1px solid #fed7aa">₿ BTC {btc_price_str}</span>
  </div>

  {_section_header("①", "Il quadro di oggi")}

  {hero}

  {therm}

  {dca}

  {_section_header("②", "Perché il modello lo suggerisce")}

  {indicators}

  {_section_header("③", "Contesto &amp; sentiment di mercato")}

  <p style="margin:-4px 0 14px;color:#94a3b8;font-size:0.88em">
    Radar di segnali rari e affidabili — si accendono solo quando c'è qualcosa da notare.
  </p>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-bottom:24px">
    {regime_banner}
    {pi_cycle_alert}
    {hash_alert}
    {golden_death}
    {divergence_banner}
    {maturity_alert}
  </div>

  <p style="margin:8px 0 16px;color:#94a3b8;font-size:0.88em">
    Le voci seguenti sono <b>informazioni esterne al modello</b>: utili come contorno, <b>non entrano nel punteggio composite</b>.
  </p>

  {external_widget}

  {_section_header("④", "Ha funzionato storicamente?")}

  <div class="card">
    <h2 style="margin:0 0 8px;font-size:1.1em">📈 Come ha funzionato il modello nella storia</h2>
    <p style="margin:0 0 6px;color:#475569;font-size:0.92em">Verifica dell'efficacia storica dei segnali, sovrapposti al prezzo di Bitcoin:</p>
    <ul style="margin:0 0 14px;padding-left:18px;color:#475569;font-size:0.92em;line-height:1.6">
      <li><b>Minimi di ciclo</b> — ha individuato i bottom 2018, 2020 e 2022: lì indicava la massima intensità di accumulo</li>
      <li><b>Massimi di ciclo</b> — al top di aprile 2021 (~$62k), prima del calo del −50%, indicava di ridurre l'accumulo al minimo e costituire riserva (senza mai liquidare)</li>
      <li><b>Divergenze RSI (✕)</b> — possibili inversioni di tendenza (verde = al rialzo, rossa = al ribasso)</li>
    </ul>
    {history_chart}
    {_chart_legend()}
  </div>

  {changes_table}

  <div class="disclaimer">
    <b>⚠️ Importante.</b> Questo strumento è un cruscotto probabilistico, <b>non un consiglio finanziario</b>.
    Si basa su 3 cicli completi di BTC (top 2017, 2021, 2024-25): la statistica ha intervalli di confidenza ampi.
    <b>Il fatto che il modello abbia funzionato in passato non garantisce che funzioni in futuro.</b>
    Con l'arrivo degli ETF spot dal 2024, alcuni pattern storici potrebbero essere strutturalmente cambiati.
    Usa questi segnali come una <b>seconda opinione</b>, mai come unica fonte di decisione.
    Definisci sempre il tuo limite di rischio prima di agire.
  </div>
</div>
</body>
</html>"""

    out = DASHBOARD_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def build_email_html(result: dict) -> str:
    """Email semplice (legacy, ora usato il bot Telegram)."""
    return f"<html><body><pre>{result}</pre></body></html>"
