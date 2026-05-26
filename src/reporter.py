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


ZONE_TO_SIMPLE = {
    "red":     ("🔴", "Negativo",  "#dc2626"),
    "orange":  ("🟠", "Cauto",     "#f97316"),
    "neutral": ("⚪", "Neutro",    "#94a3b8"),
    "lime":    ("🟢", "Positivo",  "#22c55e"),
    "green":   ("🟢", "Favorevole","#16a34a"),
    "n/a":     ("❔", "n/d",       "#cbd5e1"),
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
    <div style="text-align:right;min-width:200px">
      <div style="font-size:0.85em;color:{detail['color']};opacity:0.85;text-transform:uppercase;letter-spacing:1px">Esposizione consigliata</div>
      <div style="font-size:3.4em;font-weight:800;color:{detail['color']};line-height:1">{target}%</div>
      <div style="font-size:0.85em;color:#475569;margin-top:8px">del tuo capitale investito in BTC</div>
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
  <p style="margin:0 0 16px;color:#64748b;font-size:0.95em">
    <b style="color:#16a34a">{result['green_count']} favorevoli</b> all'acquisto ·
    <b style="color:#dc2626">{result['red_count']} negativi</b> ·
    {9 - result['green_count'] - result['red_count']} neutri
  </p>
  <table style="width:100%;border-collapse:separate;border-spacing:0 4px">
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>
"""


def _action_box(result: dict) -> str:
    detail = SIGNAL_DETAIL.get(result["signal"], SIGNAL_DETAIL["HOLD"])
    target = result["target_btc_exposure_pct"]

    if result["signal"] == "STRONG_BUY":
        steps = [
            f"<b>Allocazione target</b>: porta il <b>{target}%</b> del tuo capitale di investimento in BTC.",
            "<b>Modalità d'ingresso</b>: se sei sotto target, entra in 2-3 tranche nei prossimi 7-14 giorni (DCA).",
            "<b>Cosa monitorare</b>: il modello rimarrà in zona BUY finché 4+ indicatori sono favorevoli. Ti avviso quando cambia.",
        ]
    elif result["signal"] == "ACCUMULATE":
        steps = [
            f"<b>Allocazione target</b>: alza l'esposizione BTC verso il <b>{target}%</b>.",
            "<b>Modalità d'ingresso</b>: piccoli buy settimanali, niente fretta.",
            "<b>Cosa monitorare</b>: se il composite scende sotto 20, passiamo a STRONG_BUY → accelera.",
        ]
    elif result["signal"] == "HOLD":
        steps = [
            f"<b>Allocazione target</b>: mantieni l'esposizione attuale (modello indica {target}%).",
            "<b>Trend follow</b>: niente azioni nuove. Aspetta il prossimo segnale.",
            "<b>Cosa monitorare</b>: variazioni significative del composite (±15 punti in pochi giorni = attenzione).",
        ]
    elif result["signal"] == "DERISK":
        steps = [
            f"<b>Allocazione target</b>: riduci l'esposizione BTC verso il <b>{target}%</b>.",
            "<b>Modalità d'uscita</b>: vendi in 2-3 tranche, evita panic-selling tutto subito.",
            "<b>Cosa monitorare</b>: se il composite passa sopra 80, è STRONG_SELL → completa la riduzione.",
        ]
    else:  # STRONG_SELL
        steps = [
            f"<b>Allocazione target</b>: riduci immediatamente al <b>{target}%</b>.",
            "<b>Modalità d'uscita</b>: il modello vede confluenza di top di ciclo. Storicamente 50-85% drawdown nei 12 mesi successivi.",
            "<b>Cosa monitorare</b>: i drawdown reali servono per i prossimi BUY. Pazienza.",
        ]

    steps_html = "".join(f"<li style='margin-bottom:8px'>{s}</li>" for s in steps)

    return f"""
<div class="card" style="background:{detail['bg']};border-left:4px solid {detail['border']}">
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


def _history_with_signals(history: pd.DataFrame) -> str:
    """Grafico unico: prezzo BTC log con punti scatter colorati ai cambi di signal."""
    if history is None or history.empty:
        return ""

    h = history.copy().sort_values("date").reset_index(drop=True)
    h["signal_prev"] = h["signal"].shift(1)
    changes = h[h["signal"] != h["signal_prev"]].dropna(subset=["signal_prev"])

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.65, 0.35],
        subplot_titles=("Prezzo BTC con i segnali del modello sovrapposti",
                        "Composite score storico (0=compra, 100=vendi)"),
    )

    fig.add_trace(go.Scatter(
        x=h["date"], y=h["btc_close"], name="BTC", mode="lines",
        line=dict(color="#0f172a", width=1.4),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        showlegend=False,
    ), row=1, col=1)

    for sig, color, marker, name in [
        ("STRONG_BUY",  "#16a34a", "triangle-up",   "🟢 COMPRA FORTE"),
        ("ACCUMULATE",  "#86efac", "circle",        "🌱 Accumula"),
        ("DERISK",      "#fb923c", "circle",        "🟠 Riduci"),
        ("STRONG_SELL", "#dc2626", "triangle-down", "🔴 VENDI FORTE"),
    ]:
        sub = changes[changes["signal"] == sig]
        if len(sub):
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub["btc_close"], mode="markers", name=name,
                marker=dict(color=color, size=12, symbol=marker,
                            line=dict(color="white", width=1.5)),
                hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<br><b>" + sig + "</b><extra></extra>",
            ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=h["date"], y=h["composite_score"], name="Composite",
        line=dict(color="#475569", width=1.2),
        hovertemplate="%{x|%Y-%m-%d}<br>Score: %{y:.0f}<extra></extra>",
        showlegend=False,
    ), row=2, col=1)
    fig.add_hrect(y0=80, y1=100, fillcolor="#dc2626", opacity=0.10, line_width=0, row=2, col=1)
    fig.add_hrect(y0=0,  y1=20,  fillcolor="#16a34a", opacity=0.10, line_width=0, row=2, col=1)

    for date_str, label, kind in CYCLE_ANNOTATIONS_HUMAN:
        ts = pd.to_datetime(date_str)
        if ts < h["date"].min() or ts > h["date"].max():
            continue
        col = "#dc2626" if kind == "top" else "#16a34a"
        fig.add_vline(x=ts, line=dict(color=col, width=1, dash="dot"), row="all", col=1)

    fig.update_yaxes(type="log", title_text="USD (log)", row=1, col=1)
    fig.update_yaxes(range=[0, 100], title_text="score", row=2, col=1)
    fig.update_layout(
        template="plotly_white",
        height=620,
        margin=dict(l=50, r=20, t=60, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.10, x=0.5, xanchor="center", font=dict(size=11)),
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="chart-history")


def _recent_signal_changes(history: pd.DataFrame, n: int = 8) -> str:
    if history is None or history.empty:
        return ""
    h = history.copy().sort_values("date").reset_index(drop=True)
    h["signal_prev"] = h["signal"].shift(1)
    changes = h[h["signal"] != h["signal_prev"]].dropna(subset=["signal_prev"]).tail(n).iloc[::-1]
    if not len(changes):
        return ""

    rows = []
    for _, r in changes.iterrows():
        prev = r["signal_prev"]
        curr = r["signal"]
        d_prev = SIGNAL_DETAIL.get(prev, SIGNAL_DETAIL["HOLD"])
        d_curr = SIGNAL_DETAIL.get(curr, SIGNAL_DETAIL["HOLD"])
        rows.append(f"""<tr>
          <td style="padding:10px 12px;color:#475569">{r['date'].date()}</td>
          <td style="padding:10px 12px;font-family:monospace">${r['btc_close']:,.0f}</td>
          <td style="padding:10px 12px;color:{d_prev['color']}">{d_prev['emoji']} {prev}</td>
          <td style="padding:10px 12px;color:#475569">→</td>
          <td style="padding:10px 12px;font-weight:600;color:{d_curr['color']}">{d_curr['emoji']} {curr}</td>
        </tr>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 8px;font-size:1.1em">📜 Ultimi cambi di segnale</h2>
  <p style="margin:0 0 12px;color:#64748b;font-size:0.95em">Ogni volta che il modello cambia idea, lo trovi qui. Utile per vedere quanto spesso e in che circostanze.</p>
  <table style="width:100%;border-collapse:collapse">
    <thead><tr style="background:#f1f5f9;color:#475569;font-size:0.85em;text-transform:uppercase;letter-spacing:1px">
      <th style="padding:8px 12px;text-align:left">Data</th>
      <th style="padding:8px 12px;text-align:left">BTC</th>
      <th style="padding:8px 12px;text-align:left">Prima</th>
      <th style="padding:8px 12px"></th>
      <th style="padding:8px 12px;text-align:left">Adesso</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>
"""


def _signal_distribution(history: pd.DataFrame) -> str:
    """Quanto tempo abbiamo passato in ciascuno stato."""
    if history is None or history.empty:
        return ""
    counts = history["signal"].value_counts()
    total = counts.sum()
    order = ["STRONG_BUY", "ACCUMULATE", "HOLD", "DERISK", "STRONG_SELL"]

    bars = []
    for sig in order:
        n = int(counts.get(sig, 0))
        pct = 100 * n / total if total else 0
        d = SIGNAL_DETAIL.get(sig, SIGNAL_DETAIL["HOLD"])
        bars.append(f"""
<div style="margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;font-size:0.9em;margin-bottom:4px">
    <span style="color:{d['color']};font-weight:600">{d['emoji']} {sig}</span>
    <span style="color:#64748b">{n} giorni · {pct:.1f}%</span>
  </div>
  <div style="height:10px;background:#f1f5f9;border-radius:5px;overflow:hidden">
    <div style="height:100%;width:{pct:.1f}%;background:{d['border']}"></div>
  </div>
</div>""")

    return f"""
<div class="card">
  <h2 style="margin:0 0 8px;font-size:1.1em">📊 Storico: dove abbiamo passato il tempo</h2>
  <p style="margin:0 0 16px;color:#64748b;font-size:0.95em">Distribuzione dei segnali sugli ultimi {total} giorni (dal {history['date'].min().date()}). I top sono rari, l'accumulazione è frequente.</p>
  {''.join(bars)}
</div>
"""


def build_dashboard(result: dict, ind_df: pd.DataFrame, history: pd.DataFrame | None = None) -> Path:
    hero = _hero_banner(result)
    therm = _thermometer(result)
    action = _action_box(result)
    indicators = _indicators_table_human(result)
    history_chart = _history_with_signals(history) if history is not None else ""
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
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f8fafc; color: #0f172a; margin: 0; padding: 24px 16px; }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ margin: 0 0 6px; font-size: 1.4em; }}
  .meta {{ color: #64748b; margin-bottom: 24px; font-size: 0.95em; }}
  .card {{ background: white; border-radius: 12px; padding: 24px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 20px; }}
  table {{ font-size: 0.95em; }}
  .disclaimer {{ background: #fef9e7; border-left: 4px solid #f1c40f;
                 padding: 14px 18px; border-radius: 4px; margin: 24px 0 8px;
                 color: #713f12; font-size: 0.88em; line-height: 1.5; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>BTC Composite Indicator</h1>
  <div class="meta">Aggiornamento del <b>{result['date']}</b> · BTC oggi: <b>{btc_price_str}</b></div>

  {hero}

  {action}

  {therm}

  {indicators}

  <div class="card">
    <h2 style="margin:0 0 6px;font-size:1.1em">📈 Come ha funzionato il modello nella storia</h2>
    <p style="margin:0 0 16px;color:#64748b;font-size:0.95em">
      I triangoli verdi 🟢 sono i momenti in cui il modello diceva di <b>comprare forte</b>.
      I triangoli rossi 🔴 quando diceva di <b>vendere forte</b>.
      Guardali sovrapposti al prezzo BTC: hanno avvisato in anticipo i top del 2021 ($62k → -50%) e i bottom 2018, 2020, 2022.
    </p>
    {history_chart}
  </div>

  {changes_table}

  {distribution}

  <div class="disclaimer">
    <b>⚠️ Importante.</b> Questo strumento è un cruscotto probabilistico, <b>non un consiglio finanziario</b>.
    Si basa su 3-4 cicli completi di BTC: la statistica ha intervalli di confidenza ampi.
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
