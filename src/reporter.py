"""Genera dashboard HTML statica consumer-friendly + email HTML."""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import DASHBOARD_DIR, INDICATOR_WEIGHTS
from .composite import SIGNAL_DESCRIPTIONS


SIGNAL_DETAIL = {
    "STRONG_BUY": {
        "emoji": "💚",
        "label": "OCCASIONE D'INGRESSO",
        "action": "Il modello dice che è il momento giusto per comprare aggressivamente.",
        "rationale": "Storicamente, quando il composite è in questa zona BTC ha registrato rally del 300-700% nei 12-24 mesi successivi (bottom 2018, 2020, 2022).",
        "color":   "#15803d",
        "bg":      "#dcfce7",
        "border":  "#16a34a",
    },
    "ACCUMULATE": {
        "emoji": "🌱",
        "label": "ACCUMULA GRADUALMENTE",
        "action": "Il modello dice che siamo in una zona favorevole all'acquisto, ma senza fretta.",
        "rationale": "Diversi indicatori sono in territorio positivo. Comprare a scaglioni in queste fasi ha pagato storicamente.",
        "color":   "#166534",
        "bg":      "#d1fae5",
        "border":  "#22c55e",
    },
    "HOLD": {
        "emoji": "⚖️",
        "label": "MANTIENI POSIZIONE",
        "action": "Il modello è neutrale. Niente di particolare da fare oggi.",
        "rationale": "Il mercato non è né sopravvalutato né sottovalutato in modo significativo. Trend follow.",
        "color":   "#475569",
        "bg":      "#f1f5f9",
        "border":  "#94a3b8",
    },
    "DERISK": {
        "emoji": "🟠",
        "label": "INIZIA A RIDURRE",
        "action": "Il modello suggerisce di alleggerire progressivamente l'esposizione BTC.",
        "rationale": "Più indicatori stanno entrando in zona di surriscaldamento. Storicamente, top di ciclo si avvicinano.",
        "color":   "#9a3412",
        "bg":      "#ffedd5",
        "border":  "#f97316",
    },
    "STRONG_SELL": {
        "emoji": "🔴",
        "label": "ALLEGGERISCI FORTEMENTE",
        "action": "Il modello dice che è il momento di derisk massimo.",
        "rationale": "Quattro o più indicatori sono in zona di top storico. I cicli passati (2017, aprile 2021) hanno avuto drawdown del 50-85% subito dopo.",
        "color":   "#991b1b",
        "bg":      "#fee2e2",
        "border":  "#dc2626",
    },
}


# Etichette brevi dei segnali in italiano, allineate al termometro
# (Compra forte / Accumula / Mantieni / Riduci / Vendi forte)
SIGNAL_SHORT_IT = {
    "STRONG_BUY":  "Compra forte",
    "ACCUMULATE":  "Accumula",
    "HOLD":        "Mantieni",
    "DERISK":      "Riduci",
    "STRONG_SELL": "Vendi forte",
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


def _hero_banner(result: dict) -> str:
    """Banner gigante in cima con il signal di oggi in italiano chiaro."""
    detail = SIGNAL_DETAIL.get(result["signal"], SIGNAL_DETAIL["HOLD"])
    btc = f"${result['btc_close']:,.0f}" if result["btc_close"] else "n/a"
    target = result["target_btc_exposure_pct"]

    return f"""
<div class="hero" style="background:{detail['bg']};border:2px solid {detail['border']};border-radius:16px;padding:32px;margin-bottom:24px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap">
    <div style="flex:1;min-width:280px">
      <div style="font-size:0.95em;color:{detail['color']};opacity:0.85;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Segnale di oggi</div>
      <div style="font-size:2.4em;font-weight:700;color:{detail['color']};line-height:1.1">{detail['emoji']} {detail['label']}</div>
      <div style="font-size:1.15em;color:{detail['color']};margin-top:12px;font-weight:500">{detail['action']}</div>
      <div style="font-size:0.95em;color:#475569;margin-top:10px">{detail['rationale']}</div>
    </div>
    <div class="hero-right" style="text-align:right;min-width:200px">
      <div style="font-size:0.85em;color:{detail['color']};opacity:0.85;text-transform:uppercase;letter-spacing:1px">Allocazione BTC suggerita</div>
      <div class="big-target" style="font-size:3.4em;font-weight:800;color:{detail['color']};line-height:1">{target}%</div>
      <div style="font-size:0.8em;color:#475569;margin-top:8px;line-height:1.4">
        della <b>quota cripto/BTC</b> che hai già<br>deciso di destinare a Bitcoin<br>
        <span style="font-size:0.9em;color:#94a3b8">(non del patrimonio totale)</span>
      </div>
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
  <h2 style="margin:0 0 8px;font-size:1.1em">📊 Quanto è caro/economico BTC adesso?</h2>
  <p style="margin:0 0 20px;color:#64748b;font-size:0.95em">Composite score: <b style="color:{detail['color']}">{score:.1f} / 100</b> · più è basso, più è economico</p>
  <div style="position:relative;height:48px;border-radius:8px;overflow:hidden;background:linear-gradient(to right,#16a34a 0%,#22c55e 20%,#94a3b8 35%,#94a3b8 65%,#f97316 80%,#dc2626 100%)">
    <div style="position:absolute;left:{marker_left}%;top:-4px;bottom:-4px;width:4px;background:#0f172a;transform:translateX(-50%);box-shadow:0 0 0 2px white"></div>
    <div style="position:absolute;left:{marker_left}%;top:-28px;transform:translateX(-50%);background:#0f172a;color:white;padding:3px 8px;border-radius:6px;font-size:0.85em;font-weight:600;white-space:nowrap">{score:.0f}</div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:10px;font-size:0.78em;color:#64748b">
    <div style="text-align:center;flex:1"><b style="color:#16a34a">💚 0-20</b><br>Compra forte</div>
    <div style="text-align:center;flex:1"><b style="color:#22c55e">🌱 20-35</b><br>Accumula</div>
    <div style="text-align:center;flex:1"><b style="color:#475569">⚖️ 35-65</b><br>Mantieni</div>
    <div style="text-align:center;flex:1"><b style="color:#f97316">🟠 65-80</b><br>Riduci</div>
    <div style="text-align:center;flex:1"><b style="color:#dc2626">🔴 80-100</b><br>Vendi forte</div>
  </div>
</div>
"""


def _indicators_table_human(result: dict) -> str:
    rows = []
    for name in INDICATOR_WEIGHTS:
        info = result["indicators"].get(name, {})
        zone = info.get("zone", "n/a")
        emoji, label_simple, color = ZONE_TO_SIMPLE[zone]
        human = INDICATOR_HUMAN.get(name, {})

        rows.append(f"""<tr>
          <td style="padding:14px 12px">
            <div style="font-weight:600">{human.get('label', name)}</div>
            <div style="color:#64748b;font-size:0.85em;margin-top:2px">{human.get('what', '')}</div>
          </td>
          <td style="padding:14px 12px;text-align:center;white-space:nowrap">
            <span style="display:inline-flex;align-items:center;gap:6px;background:{color}20;color:{color};padding:6px 12px;border-radius:20px;font-weight:600;font-size:0.92em">
              {emoji} {label_simple}
            </span>
          </td>
        </tr>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 8px;font-size:1.1em">🔍 Cosa dicono i 9 indicatori</h2>
  <p style="margin:0 0 4px;color:#64748b;font-size:0.95em">
    <b style="color:#16a34a">{result.get('fav_count', 0)} favorevoli</b> all'acquisto ·
    <b style="color:#dc2626">{result.get('neg_count', 0)} negativi</b> ·
    {result.get('neu_count', 0)} neutri
  </p>
  <p style="margin:0 0 16px;color:#94a3b8;font-size:0.85em">
    Questi 9 indicatori, fusi insieme con il loro peso, producono il <b>Segnale di oggi</b> mostrato in cima alla pagina.
  </p>
  <div class="tbl-scroll"><table style="width:100%;border-collapse:separate;border-spacing:0 4px;min-width:340px">
    <tbody>{''.join(rows)}</tbody>
  </table></div>
</div>
"""


def _action_box(result: dict) -> str:
    detail = SIGNAL_DETAIL.get(result["signal"], SIGNAL_DETAIL["HOLD"])
    target = result["target_btc_exposure_pct"]

    base = "Tieni il <b>{}%</b> della <b>quota che hai destinato a BTC</b> investita in Bitcoin (il resto in stable/cash)."

    if result["signal"] == "STRONG_BUY":
        steps = [
            base.format(target),
            "<b>Modalità d'ingresso</b>: se sei sotto target, entra a scaglioni (DCA) in 2-3 tranche nei prossimi 7-14 giorni.",
            "<b>Cosa monitorare</b>: il modello resterà in zona BUY finché 4+ indicatori sono favorevoli. Ti avviso quando cambia.",
        ]
    elif result["signal"] == "ACCUMULATE":
        steps = [
            base.format(target),
            "<b>Modalità d'ingresso</b>: piccoli buy settimanali, niente fretta.",
            "<b>Cosa monitorare</b>: se il composite scende sotto 20 → passa a STRONG_BUY → accelera gli acquisti.",
        ]
    elif result["signal"] == "HOLD":
        steps = [
            base.format(target),
            "<b>Trend follow</b>: niente azioni nuove. Aspetta il prossimo segnale.",
            "<b>Cosa monitorare</b>: variazioni significative del composite (±15 punti in pochi giorni) = riapri la dashboard.",
        ]
    elif result["signal"] == "DERISK":
        steps = [
            f"<b>Riduci verso il {target}%</b> di esposizione BTC sulla tua quota cripto. Il resto in stable/cash.",
            "<b>Modalità d'uscita</b>: vendi in 2-3 tranche, evita panic-selling tutto in un colpo.",
            "<b>Cosa monitorare</b>: se il composite passa sopra 80 → STRONG_SELL → completa la riduzione.",
        ]
    else:  # STRONG_SELL
        steps = [
            f"<b>Riduci immediatamente al {target}%</b> sulla tua quota cripto destinata a BTC. Sposta il resto in stable/cash.",
            "<b>Modalità d'uscita</b>: il modello vede confluenza di top di ciclo. Storicamente 50-85% drawdown nei 12 mesi successivi.",
            "<b>Cosa monitorare</b>: i drawdown reali serviranno per i prossimi BUY. Pazienza, non FOMO.",
        ]

    steps_html = "".join(f"<li style='margin-bottom:8px'>{s}</li>" for s in steps)

    return f"""
<div class="card" style="background:{detail['bg']};border-left:4px solid {detail['border']};flex:1;min-width:300px;margin-bottom:0">
  <h2 style="margin:0 0 12px;font-size:1.1em;color:{detail['color']}">✅ Cosa fare oggi</h2>
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


def _regime_and_divergence_banner(result: dict) -> str:
    regime = result.get("regime", "BULL")
    rd = REGIME_DETAIL.get(regime, REGIME_DETAIL["BULL"])
    sma200 = result.get("sma_200w")
    sma_str = f"${sma200:,.0f}" if sma200 else "n/a"
    correction = result.get("regime_correction", False)
    corr_badge = ""
    if correction:
        corr_badge = '<span style="display:inline-block;margin-left:8px;background:#f97316;color:white;padding:2px 8px;border-radius:8px;font-size:0.7em;vertical-align:middle">IN CORREZIONE</span>'
    label_extra = " · in correzione di medio termine" if correction else ""

    # stile comune a tutti i box affiancati: ombra .card + border-left accento
    col = 'class="card" style="margin-bottom:0;flex:1;min-width:240px;border-left:4px solid {accent};background:{bg}"'

    # Divergenza RSI recente
    div = result.get("last_divergence")
    if div == "bull":
        div_html = f"""<div {col.format(accent='#16a34a', bg='#dcfce7')}>
          <div style="font-size:0.8em;color:#15803d;text-transform:uppercase;letter-spacing:1px">Divergenza RSI</div>
          <div style="font-size:1.25em;font-weight:700;color:#15803d">📈 Divergenza RIALZISTA</div>
          <div style="font-size:0.88em;color:#475569;margin-top:4px">Rilevata {result.get('last_divergence_age_days','?')} giorni fa sul weekly. Il prezzo ha fatto un nuovo minimo ma l'RSI no → possibile inversione al rialzo (segnale di reversal verso l'alto).</div>
        </div>"""
    elif div == "bear":
        div_html = f"""<div {col.format(accent='#dc2626', bg='#fee2e2')}>
          <div style="font-size:0.8em;color:#991b1b;text-transform:uppercase;letter-spacing:1px">Divergenza RSI</div>
          <div style="font-size:1.25em;font-weight:700;color:#991b1b">📉 Divergenza RIBASSISTA</div>
          <div style="font-size:0.88em;color:#475569;margin-top:4px">Rilevata {result.get('last_divergence_age_days','?')} giorni fa sul weekly. Il prezzo ha fatto un nuovo massimo ma l'RSI no → possibile inversione al ribasso (attenzione, segnale di reversal verso il basso).</div>
        </div>"""
    else:
        div_html = f"""<div {col.format(accent='#cbd5e1', bg='white')}>
          <div style="font-size:0.8em;color:#64748b;text-transform:uppercase;letter-spacing:1px">Divergenza RSI</div>
          <div style="font-size:1.25em;font-weight:700;color:#475569">➖ Nessuna divergenza recente</div>
          <div style="font-size:0.88em;color:#64748b;margin-top:4px">Nessuna divergenza prezzo/RSI significativa nelle ultime 6 settimane sul weekly. Niente segnale di inversione imminente da questo indicatore.</div>
        </div>"""

    return f"""
<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px">
  <div {col.format(accent=rd['color'], bg=rd['bg'])}>
    <div style="font-size:0.8em;color:{rd['color']};text-transform:uppercase;letter-spacing:1px">Regime di mercato</div>
    <div style="font-size:1.25em;font-weight:700;color:{rd['color']}">{rd['emoji']} {rd['label']}{corr_badge}</div>
    <div style="font-size:0.88em;color:#475569;margin-top:4px">{rd['desc']}{label_extra}</div>
    <div style="font-size:0.8em;color:#94a3b8;margin-top:6px">Media 200 settimane: {sma_str}</div>
  </div>
  {div_html}
</div>
"""


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

    dca_box = f"""
<div class="card" style="background:{d['bg']};border-left:4px solid {d['border']};margin-bottom:0;flex:1;min-width:280px">
  <h2 style="margin:0 0 6px;font-size:1.1em;color:{d['color']}">💧 Strategia di accumulo (DCA)</h2>
  <div style="font-size:1.5em;font-weight:700;color:{d['color']};margin:4px 0">{d['emoji']} DCA {dca['level']}</div>
  <div style="margin:2px 0 8px"><span style="display:inline-block;white-space:nowrap;font-size:0.78em;font-weight:600;background:{d['border']};color:white;padding:4px 12px;border-radius:12px">{d['tag']}</span></div>
  <div style="color:#475569;font-size:0.92em;line-height:1.5">{dca['reason']}</div>
  {ref}
</div>"""

    bot_box = f"""
<div class="card" style="margin-bottom:0;flex:1;min-width:280px;border-left:4px solid #64748b">
  <h2 style="margin:0 0 6px;font-size:1.1em">🤖 Istruzioni per i Bot DCA</h2>
  <div style="font-size:0.9em;margin:4px 0">
    Stato bot: <span style="font-weight:700;color:{state_color}">{bot_state}</span>
  </div>
  <div style="color:#475569;font-size:0.92em;line-height:1.5">{dca.get('bot_action','')}</div>
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
    """Widget Crypto Fear & Greed Index. Sentiment esterno al modello."""
    if not fng or not fng.get("available"):
        return ""
    v = fng["value"]
    klass_it = fng["classification_it"]
    # colore del valore secondo scala standard F&G (rosso paura → verde avidità)
    if v < 25:
        vcolor = "#dc2626"
    elif v < 45:
        vcolor = "#f97316"
    elif v < 55:
        vcolor = "#64748b"
    elif v < 75:
        vcolor = "#22c55e"
    else:
        vcolor = "#16a34a"
    marker = max(0, min(100, v))
    return f"""
<div class="card">
  <h2 style="margin:0 0 4px;font-size:1.1em">😱 Fear &amp; Greed Index</h2>
  <p style="margin:0 0 12px;color:#64748b;font-size:0.9em">Emotività del mercato crypto oggi: <b style="color:{vcolor}">{v}/100 — {klass_it}</b> · {fng['trend']}</p>
  <div style="position:relative;height:40px;border-radius:8px;overflow:hidden;background:linear-gradient(to right,#dc2626 0%,#f97316 25%,#cbd5e1 50%,#22c55e 75%,#16a34a 100%)">
    <div style="position:absolute;left:{marker}%;top:-3px;bottom:-3px;width:4px;background:#0f172a;transform:translateX(-50%);box-shadow:0 0 0 2px white"></div>
    <div style="position:absolute;left:{marker}%;top:-26px;transform:translateX(-50%);background:#0f172a;color:white;padding:2px 8px;border-radius:6px;font-size:0.82em;font-weight:700;white-space:nowrap">{v}</div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:0.75em;color:#94a3b8">
    <span>0 · Paura estrema</span><span>50 · Neutrale</span><span>Avidità estrema · 100</span>
  </div>
  <p style="margin:14px 0 0;color:#94a3b8;font-size:0.78em;line-height:1.45">
    ℹ️ Lettura <b>contrarian</b>: la paura estrema ha storicamente coinciso con buone occasioni d'acquisto,
    l'avidità estrema con i top. È <b>contesto esterno</b>, non entra nel punteggio composite.
  </p>
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

    # barra sentiment a 3 segmenti
    bar = f"""
<div style="display:flex;height:14px;border-radius:7px;overflow:hidden;margin:6px 0 4px">
  <div style="width:{bull}%;background:#16a34a"></div>
  <div style="width:{neu}%;background:#cbd5e1"></div>
  <div style="width:{bear}%;background:#dc2626"></div>
</div>
<div style="display:flex;justify-content:space-between;font-size:0.8em;color:#64748b;margin-bottom:16px">
  <span style="color:#16a34a;font-weight:600">🟢 {bull}% Bullish</span>
  <span>⚪ {neu}% Neutrale</span>
  <span style="color:#dc2626;font-weight:600">🔴 {bear}% Bearish</span>
</div>"""

    rows = []
    for it in news["items"]:
        emoji, _, color = NEWS_SENTIMENT.get(it["sentiment"], NEWS_SENTIMENT["neutral"])
        title = safe(it["title"])
        link = safe(it["link"])
        src = safe(it["source"])
        date_str = it["published"].strftime("%d/%m") if it.get("published") else ""
        rows.append(f"""
<a href="{link}" target="_blank" rel="noopener noreferrer"
   style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-top:1px solid #f1f5f9;text-decoration:none;color:inherit">
  <span style="font-size:0.95em;flex-shrink:0">{emoji}</span>
  <span style="flex:1;min-width:0">
    <span style="font-size:0.93em;color:#1e293b;font-weight:500">{title}</span>
    <span style="display:block;font-size:0.78em;color:#94a3b8;margin-top:2px">{src} · {date_str} ↗</span>
  </span>
</a>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 4px;font-size:1.1em">📰 Macro Sentiment &amp; Breaking News</h2>
  <p style="margin:0 0 6px;color:#64748b;font-size:0.9em">
    Clima delle notizie crypto di oggi: <b style="color:{label_color}">{label}</b>
    <span style="color:#94a3b8">(su {news['total']} testate analizzate)</span>
  </p>
  {bar}
  <div>{''.join(rows)}</div>
  <p style="margin:14px 0 0;color:#94a3b8;font-size:0.78em;line-height:1.45">
    ℹ️ Le notizie sono <b>contesto</b>, non un segnale operativo: il sentiment dei titoli è rumoroso e
    <b>non entra nel punteggio composite</b>. Quando una notizia è pubblica, il movimento di prezzo è spesso già avvenuto.
  </p>
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
            f'<td style="padding:10px 12px">{_outcome_cell(curr, float(r["btc_close"]), price_at_horizon(r["date"], hz))}</td>'
            for hz in horizons
        )
        rows.append(f"""<tr>
          <td style="padding:10px 12px;color:#475569">{r['date'].date()}</td>
          <td style="padding:10px 12px;font-family:monospace">${r['btc_close']:,.0f}</td>
          <td style="padding:10px 12px;font-weight:600;color:{d_curr['color']}">{d_curr['emoji']} {curr_it}</td>
          {cells}
        </tr>""")

    esito_headers = "".join(
        f'<th style="padding:8px 12px;text-align:left">Esito {hz}gg</th>' for hz in horizons
    )
    return f"""
<div class="card">
  <h2 style="margin:0 0 6px;font-size:1.1em">📜 Ultimi cambi di segnale</h2>
  <p style="margin:0 0 10px;color:#64748b;font-size:0.92em">
    Ogni riga è un momento in cui il <b>segnale operativo è cambiato</b> rispetto al precedente
    (es. da <i>Mantieni</i> ad <i>Accumula</i>): accade quando il punteggio composite supera una soglia.
    Può succedere a distanza di settimane o mesi. Mostriamo i cambi degli <b>ultimi ~6 mesi</b>.
  </p>
  <p style="margin:0 0 12px;color:#64748b;font-size:0.92em">
    Le colonne <b>Esito</b> dicono se la mossa si è poi rivelata corretta a <b>30, 90 e 180 giorni</b>
    (prezzo andato nella direzione attesa). Più lungo è l'orizzonte, più conta per l'accumulo.
    Misura <i>indicativa</i>; trattino grigio = orizzonte non ancora maturo.
    <b>Aver funzionato in passato non garantisce risultati futuri.</b>
  </p>
  <div class="tbl-scroll"><table style="width:100%;border-collapse:collapse;min-width:560px">
    <thead><tr style="background:#f1f5f9;color:#475569;font-size:0.85em;text-transform:uppercase;letter-spacing:1px">
      <th style="padding:8px 12px;text-align:left">Data</th>
      <th style="padding:8px 12px;text-align:left">BTC</th>
      <th style="padding:8px 12px;text-align:left">Nuovo segnale</th>
      {esito_headers}
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
</div>
"""


def _signal_distribution(history: pd.DataFrame) -> str:
    """Quanto tempo abbiamo passato in ciascuno stato."""
    if history is None or history.empty:
        return ""
    h = history.copy().sort_values("date").reset_index(drop=True)
    counts = h["signal"].value_counts()
    total = counts.sum()
    order = ["STRONG_BUY", "ACCUMULATE", "HOLD", "DERISK", "STRONG_SELL"]

    # Fase corrente + da quanti giorni dura
    current = h["signal"].iloc[-1]
    streak = 1
    for s in h["signal"].iloc[::-1][1:]:
        if s == current:
            streak += 1
        else:
            break

    # Durata media storica delle fasi dello stesso tipo (run consecutivi)
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
    avg_dur = round(sum(same) / len(same)) if same else streak

    d_cur = SIGNAL_DETAIL.get(current, SIGNAL_DETAIL["HOLD"])
    cur_it = SIGNAL_SHORT_IT.get(current, current)
    if streak > avg_dur:
        maturity = f"fase <b>matura</b> (oltre la media di {avg_dur} giorni)"
    elif streak >= avg_dur * 0.6:
        maturity = f"fase <b>in corso</b> (media storica ~{avg_dur} giorni)"
    else:
        maturity = f"fase <b>recente</b> (media storica ~{avg_dur} giorni)"

    current_box = f"""
<div style="background:{d_cur['bg']};border-left:4px solid {d_cur['border']};border-radius:8px;padding:14px 16px;margin-bottom:18px">
  <div style="font-size:0.78em;text-transform:uppercase;letter-spacing:1px;color:{d_cur['color']}">Dove sei oggi</div>
  <div style="font-size:1.15em;font-weight:700;color:{d_cur['color']};margin:2px 0">{d_cur['emoji']} {cur_it} — da {streak} giorni</div>
  <div style="font-size:0.88em;color:#475569">{maturity}</div>
</div>"""

    bars = []
    for sig in order:
        n = int(counts.get(sig, 0))
        pct = 100 * n / total if total else 0
        d = SIGNAL_DETAIL.get(sig, SIGNAL_DETAIL["HOLD"])
        sig_it = SIGNAL_SHORT_IT.get(sig, sig)
        is_cur = sig == current
        name_style = f"color:{d['color']};font-weight:700" if is_cur else f"color:{d['color']};font-weight:600"
        dot = " 📍" if is_cur else ""
        bars.append(f"""
<div style="margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;font-size:0.9em;margin-bottom:4px">
    <span style="{name_style}">{d['emoji']} {sig_it}{dot}</span>
    <span style="color:#64748b">{n} giorni · {pct:.1f}%</span>
  </div>
  <div style="height:10px;background:#f1f5f9;border-radius:5px;overflow:hidden{';outline:2px solid '+d['border'] if is_cur else ''}">
    <div style="height:100%;width:{pct:.1f}%;background:{d['border']}"></div>
  </div>
</div>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 8px;font-size:1.1em">📊 Distribuzione storica dei segnali</h2>
  {current_box}
  <p style="margin:0 0 16px;color:#64748b;font-size:0.95em">Ripartizione percentuale dei segnali del modello sugli ultimi {total} giorni (dal {h['date'].min().date()}). I top sono rari, l'accumulo è frequente.</p>
  {''.join(bars)}
</div>
"""


def _explain_target(result: dict) -> str:
    target = result["target_btc_exposure_pct"]
    return f"""
<div class="card" style="background:#eff6ff;border-left:4px solid #3b82f6;flex:1;min-width:300px;margin-bottom:0">
  <h2 style="margin:0 0 8px;font-size:1em;color:#1e40af">ℹ️ Come si legge questo {target}%</h2>
  <p style="margin:0;color:#1e3a8a;font-size:0.92em;line-height:1.55">
    Il modello assume che tu abbia <b>già deciso quanto del tuo patrimonio destinare a BTC</b>
    (es. il 5%, il 20%, il 60% — è una scelta personale che dipende dalla tua tolleranza al rischio).<br><br>
    Questo <b>{target}%</b> ti dice <b>come allocare quella quota</b>: oggi tienine il {target}% in Bitcoin
    e il restante {round(100 - target, 1)}% in stablecoin/cash, pronto a entrare se il segnale si rafforza.
    <b>Non è una raccomandazione su quanto del tuo patrimonio investire in BTC.</b>
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
        it("▲", "#16a34a", "Compra forte"),
        it("●", "#4ade80", "Accumula"),
        it("●", "#fb923c", "Riduci"),
        it("▼", "#dc2626", "Vendi forte"),
    ])
    momento = " &nbsp;·&nbsp; ".join([
        it("✕", "#16a34a", "Div. rialzista"),
        it("✕", "#dc2626", "Div. ribassista"),
    ])
    return f"""
<div style="margin-top:8px;border-top:1px solid #f1f5f9;padding-top:12px">
  <div style="font-size:0.72em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:6px">Segnali di tendenza</div>
  <div style="display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:12px">{tendenza}</div>
  <div style="font-size:0.72em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:6px">Indicatori di momento</div>
  <div style="display:flex;flex-wrap:wrap;gap:6px 14px">{momento}</div>
</div>"""


def _section_header(num: str, title: str) -> str:
    return f"""
<div style="margin:36px 0 16px">
  <div style="font-size:1.2em;font-weight:700;color:#0f172a">{num}&nbsp;&nbsp;{title}</div>
  <div style="height:2px;background:linear-gradient(to right,#94a3b8,#e2e8f0 60%,transparent);margin-top:8px"></div>
</div>"""


def build_dashboard(result: dict, ind_df: pd.DataFrame, history: pd.DataFrame | None = None,
                    divergences: pd.DataFrame | None = None, news: dict | None = None,
                    fng: dict | None = None) -> Path:
    hero = _hero_banner(result)
    regime_div = _regime_and_divergence_banner(result)
    dca = _dca_and_bot_row(result)
    therm = _thermometer(result)
    action = _action_box(result)
    explain = _explain_target(result)
    indicators = _indicators_table_human(result)
    fng_widget = _fear_greed_widget(fng)
    news_widget = _news_widget(news)
    history_chart = _history_with_signals(history, divergences=divergences) if history is not None else ""
    changes_table = _recent_signal_changes(history) if history is not None else ""
    distribution = _signal_distribution(history) if history is not None else ""

    btc_price = result["btc_close"]
    btc_price_str = f"${btc_price:,.0f}" if btc_price else "n/a"

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
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
    BTC Composite Indicator
    <span style="font-size:0.5em;font-weight:700;letter-spacing:1px;background:#e0e7ff;color:#4338ca;padding:3px 9px;border-radius:6px;vertical-align:middle">BETA</span>
    <span style="font-size:0.5em;font-weight:700;letter-spacing:1px;background:#dcfce7;color:#15803d;padding:3px 9px;border-radius:6px;vertical-align:middle">ACCUMULO · DCA</span>
  </h1>
  <div class="tagline">Quando accumulare e quando alleggerire Bitcoin, in un colpo d'occhio</div>
  <div style="color:#64748b;font-size:0.85em;margin-bottom:6px">Strumento di accumulo a lungo termine — non trading speculativo</div>
  <div class="meta">Aggiornamento del <b>{result['date']}</b> · BTC oggi: <b>{btc_price_str}</b></div>

  {_section_header("①", "Il quadro di oggi")}

  {hero}

  {therm}

  {dca}

  <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px">
    {action}
    {explain}
  </div>

  {_section_header("②", "Perché il modello lo suggerisce")}

  {regime_div}

  {indicators}

  {_section_header("③", "Contesto &amp; sentiment di mercato")}

  <p style="margin:-4px 0 16px;color:#94a3b8;font-size:0.88em">
    Informazioni esterne al modello: utili come contorno, <b>non entrano nel punteggio composite</b>.
  </p>

  {fng_widget}

  {news_widget}

  {_section_header("④", "Ha funzionato storicamente?")}

  <div class="card">
    <h2 style="margin:0 0 8px;font-size:1.1em">📈 Come ha funzionato il modello nella storia</h2>
    <p style="margin:0 0 6px;color:#475569;font-size:0.92em">Verifica dell'efficacia storica dei segnali, sovrapposti al prezzo di Bitcoin:</p>
    <ul style="margin:0 0 14px;padding-left:18px;color:#475569;font-size:0.92em;line-height:1.6">
      <li><b>Minimi di ciclo</b> — ha individuato i bottom 2018, 2020 e 2022 (zone di accumulo)</li>
      <li><b>Allerta sui massimi</b> — segnalò il top di aprile 2021 (~$62k) prima del calo del −50%</li>
      <li><b>Divergenze RSI (✕)</b> — possibili inversioni di tendenza (verde = al rialzo, rossa = al ribasso)</li>
    </ul>
    {history_chart}
    {_chart_legend()}
  </div>

  {distribution}

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
