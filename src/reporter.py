"""Genera dashboard HTML statica con grafici Plotly + email HTML."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import DASHBOARD_DIR, INDICATOR_WEIGHTS
from .composite import SIGNAL_DESCRIPTIONS

ZONE_COLORS = {
    "red":     "#c0392b",
    "orange":  "#e67e22",
    "neutral": "#7f8c8d",
    "lime":    "#27ae60",
    "green":   "#16a085",
    "n/a":     "#bdc3c7",
}

SIGNAL_COLORS = {
    "STRONG_SELL": "#c0392b",
    "DERISK":      "#e67e22",
    "HOLD":        "#7f8c8d",
    "ACCUMULATE":  "#27ae60",
    "STRONG_BUY":  "#16a085",
}

INDICATOR_LABELS = {
    "pi_cycle":     "Pi Cycle Top (111DMA / 350DMA×2)",
    "mayer":        "Mayer Multiple (price / 200DMA)",
    "two_year_ma":  "2-Year MA Multiplier (price / 730DMA)",
    "mvrv_z":       "MVRV Z-Score",
    "rsi_weekly":   "RSI Weekly (14)",
    "nupl":         "NUPL (Net Unrealized P/L)",
    "puell":        "Puell Multiple",
    "hash_ribbons": "Hash Ribbons (30D/60D hash rate)",
    "bmsb":         "Bull Market Support Band ratio",
}

INDICATOR_NOTES = {
    "pi_cycle":     "≥0.95 = top zone storica (2013, 2017, 2021)",
    "mayer":        ">2.4 = top zone; <1.0 = accumulazione",
    "two_year_ma":  ">4 = banda blow-off; <1 = bottom storici",
    "mvrv_z":       ">6 = top ciclo; <0 = bottom ciclo",
    "rsi_weekly":   ">85 con divergenza = top; <35 = bottom",
    "nupl":         ">0.75 = euphoria/top; <0 = capitulation",
    "puell":        ">3.5 = top miner profitability; <0.5 = bottom",
    "hash_ribbons": "Buy cross dopo capitulation = bottom signal",
    "bmsb":         ">1.30 = estensione; <1.0 = sotto la band (bear)",
}


def _format_value(v, indicator: str) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if isinstance(v, bool):
        return "Sì" if v else "No"
    if indicator in ("mvrv_z", "rsi_weekly", "puell"):
        return f"{v:.2f}"
    if indicator in ("mayer", "two_year_ma", "bmsb", "hash_ribbons"):
        return f"{v:.3f}"
    if indicator == "pi_cycle":
        return f"{v:.3f}"
    if indicator == "nupl":
        return f"{v:.3f}"
    return f"{v:.4f}"


def _price_chart(ind_df: pd.DataFrame) -> str:
    """Grafico prezzo BTC log + 200DMA + 350DMA×2 + 111DMA."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ind_df["date"], y=ind_df["close"], name="BTC close",
        line=dict(color="#f39c12", width=1.5),
    ))
    fig.add_trace(go.Scatter(
        x=ind_df["date"], y=ind_df["dma_200"], name="200 DMA",
        line=dict(color="#3498db", width=1, dash="dot"),
    ))
    fig.add_trace(go.Scatter(
        x=ind_df["date"], y=ind_df["dma_111"], name="111 DMA",
        line=dict(color="#9b59b6", width=1, dash="dot"),
    ))
    fig.add_trace(go.Scatter(
        x=ind_df["date"], y=ind_df["dma_350x2"], name="350 DMA × 2",
        line=dict(color="#e74c3c", width=1, dash="dash"),
    ))
    fig.update_layout(
        template="plotly_white",
        yaxis=dict(type="log", title="Prezzo USD (log)"),
        xaxis=dict(title=""),
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(orientation="h", y=1.1),
        height=420,
        title="Prezzo BTC + Pi Cycle Top components",
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="chart-price")


CYCLE_ANNOTATIONS = [
    ("2017-12-17", "top dic 2017",  "top"),
    ("2018-12-15", "bottom 2018",   "bot"),
    ("2020-03-12", "covid crash",   "bot"),
    ("2021-04-14", "top apr 2021",  "top"),
    ("2021-11-10", "top nov 2021",  "top"),
    ("2022-11-21", "bottom 2022",   "bot"),
    ("2024-03-14", "ATH pre-halving", "top"),
]


def _composite_chart(history: pd.DataFrame) -> str:
    """Storico del composite score con annotation sui top/bottom storici."""
    if history is None or history.empty:
        return ""

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.6, 0.4],
        subplot_titles=("Composite score storico (0-100)", "Prezzo BTC (log)"),
    )

    fig.add_trace(go.Scatter(
        x=history["date"], y=history["composite_score"], name="Composite",
        line=dict(color="#2c3e50", width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>Score: %{y:.1f}<extra></extra>",
    ), row=1, col=1)

    fig.add_hrect(y0=80, y1=100, fillcolor="#c0392b", opacity=0.12, line_width=0, row=1, col=1)
    fig.add_hrect(y0=65, y1=80,  fillcolor="#e67e22", opacity=0.08, line_width=0, row=1, col=1)
    fig.add_hrect(y0=20, y1=35,  fillcolor="#27ae60", opacity=0.08, line_width=0, row=1, col=1)
    fig.add_hrect(y0=0,  y1=20,  fillcolor="#16a085", opacity=0.12, line_width=0, row=1, col=1)

    fig.add_trace(go.Scatter(
        x=history["date"], y=history["btc_close"], name="BTC close",
        line=dict(color="#f39c12", width=1.2),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    for date_str, label, kind in CYCLE_ANNOTATIONS:
        ts = pd.to_datetime(date_str)
        if ts < history["date"].min() or ts > history["date"].max():
            continue
        color = "#c0392b" if kind == "top" else "#16a085"
        fig.add_vline(x=ts, line=dict(color=color, width=1, dash="dot"), row="all", col=1)
        fig.add_annotation(x=ts, y=95 if kind == "top" else 5, text=label,
                            showarrow=False, font=dict(size=10, color=color),
                            xref="x", yref="y", row=1, col=1)

    fig.update_yaxes(range=[0, 100], row=1, col=1)
    fig.update_yaxes(type="log", row=2, col=1)
    fig.update_layout(
        template="plotly_white",
        height=560,
        margin=dict(l=40, r=20, t=60, b=40),
        showlegend=False,
        hovermode="x unified",
    )
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id="chart-composite")


def _gauge(score: float, signal: str) -> str:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": f"<b>{signal}</b>", "font": {"size": 22}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar":  {"color": SIGNAL_COLORS.get(signal, "#34495e")},
            "steps": [
                {"range": [0, 20],   "color": "#a3e4d7"},
                {"range": [20, 35],  "color": "#d4efdf"},
                {"range": [35, 65],  "color": "#fdfefe"},
                {"range": [65, 80],  "color": "#fadbd8"},
                {"range": [80, 100], "color": "#f5b7b1"},
            ],
        },
    ))
    fig.update_layout(margin=dict(l=20, r=20, t=60, b=20), height=300)
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id="chart-gauge")


def build_dashboard(result: dict, ind_df: pd.DataFrame, history: pd.DataFrame | None = None) -> Path:
    rows = []
    for name in INDICATOR_WEIGHTS:
        info = result["indicators"].get(name, {})
        zone = info.get("zone", "n/a")
        score = info.get("score")
        rows.append({
            "label":  INDICATOR_LABELS[name],
            "value":  _format_value(info.get("value"), name),
            "score":  f"{score:.1f}" if isinstance(score, (int, float)) else "n/a",
            "zone":   zone,
            "color":  ZONE_COLORS[zone],
            "weight": f"{info.get('weight', 0)*100:.0f}%",
            "note":   INDICATOR_NOTES[name],
        })

    table_html = "\n".join(
        f"""<tr>
              <td>{r['label']}</td>
              <td style="text-align:right;font-family:monospace">{r['value']}</td>
              <td style="text-align:right;font-family:monospace">{r['score']}</td>
              <td><span style="background:{r['color']};color:white;padding:3px 10px;border-radius:12px;font-size:0.85em">{r['zone']}</span></td>
              <td style="text-align:right">{r['weight']}</td>
              <td style="color:#7f8c8d;font-size:0.9em">{r['note']}</td>
            </tr>"""
        for r in rows
    )

    gauge_html = _gauge(result["composite_score"], result["signal"])
    price_html = _price_chart(ind_df.tail(365 * 5))  # ultimi 5 anni
    composite_history_html = _composite_chart(history) if history is not None else ""

    signal_desc = SIGNAL_DESCRIPTIONS.get(result["signal"], "")
    btc_price = result["btc_close"]
    btc_price_str = f"${btc_price:,.0f}" if btc_price else "n/a"
    target = result["target_btc_exposure_pct"]

    html = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BTC Composite Indicator — {result['date']}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f4f6f8; color: #2c3e50; margin: 0; padding: 24px; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px; font-size: 1.5em; }}
  .meta {{ color: #7f8c8d; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .card {{ background: white; border-radius: 12px; padding: 20px;
           box-shadow: 0 1px 4px rgba(0,0,0,0.05); }}
  .big-num {{ font-size: 2.2em; font-weight: 600; margin: 8px 0; }}
  .target {{ font-size: 1.8em; font-weight: 600; color: {SIGNAL_COLORS.get(result['signal'], '#2c3e50')}; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid #ecf0f1; text-align: left; }}
  th {{ background: #ecf0f1; font-weight: 500; font-size: 0.9em; }}
  .disclaimer {{ background: #fef9e7; border-left: 3px solid #f1c40f;
                 padding: 12px 16px; border-radius: 4px; margin-top: 24px;
                 color: #7d6608; font-size: 0.9em; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>BTC Composite Indicator</h1>
  <div class="meta">Snapshot del {result['date']} · {btc_price_str} · generato dallo script btc-tool</div>

  <div class="grid">
    <div class="card">
      {gauge_html}
      <p style="margin-top:0;color:#7f8c8d;">{signal_desc}</p>
    </div>
    <div class="card">
      <div style="color:#7f8c8d">Target esposizione BTC (sigmoide del composite score)</div>
      <div class="target">{target}%</div>
      <div style="margin-top:12px;color:#7f8c8d">
        <strong>Indicatori in red zone:</strong> {result['red_count']} su {len(result['indicators'])}<br>
        <strong>Indicatori in green zone:</strong> {result['green_count']} su {len(result['indicators'])}<br>
        <strong>Composite score:</strong> {result['composite_score']}/100
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:24px;">
    <h2 style="margin-top:0;font-size:1.1em;">Dettaglio 9 indicatori</h2>
    <table>
      <thead>
        <tr><th>Indicatore</th><th style="text-align:right">Valore</th><th style="text-align:right">Score</th><th>Zone</th><th style="text-align:right">Peso</th><th>Soglie storiche</th></tr>
      </thead>
      <tbody>
        {table_html}
      </tbody>
    </table>
  </div>

  <div class="card" style="margin-bottom:24px;">{price_html}</div>
  {f'<div class="card" style="margin-bottom:24px;">{composite_history_html}</div>' if composite_history_html else ''}

  <div class="disclaimer">
    <strong>Non è investment advice.</strong> Questo strumento aggrega indicatori storicamente correlati con i top/bottom di ciclo BTC.
    Il sample size è di sole 3–4 cicli completi: ogni statistica ha un intervallo di confidenza ampio.
    Con l'arrivo degli ETF spot dal 2024, il pattern storico potrebbe essere strutturalmente cambiato.
    Usa il composite come <em>cruscotto di rischio probabilistico</em>, non come crystal ball.
    Definisci sempre criteri di invalidation prima di prendere posizione.
  </div>
</div>
</body>
</html>"""

    out = DASHBOARD_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def build_email_html(result: dict) -> str:
    rows = []
    for name in INDICATOR_WEIGHTS:
        info = result["indicators"].get(name, {})
        zone = info.get("zone", "n/a")
        score = info.get("score")
        rows.append(
            f"<tr><td style='padding:6px 12px'>{INDICATOR_LABELS[name]}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-family:monospace'>{_format_value(info.get('value'), name)}</td>"
            f"<td style='padding:6px 12px;text-align:right;font-family:monospace'>{score:.0f}</td>"
            f"<td style='padding:6px 12px'><span style='background:{ZONE_COLORS[zone]};color:white;padding:2px 8px;border-radius:8px;font-size:0.85em'>{zone}</span></td></tr>"
            if score is not None else
            f"<tr><td style='padding:6px 12px'>{INDICATOR_LABELS[name]}</td>"
            f"<td colspan='3' style='padding:6px 12px;color:#999'>n/a</td></tr>"
        )

    sig_color = SIGNAL_COLORS.get(result["signal"], "#2c3e50")
    btc = f"${result['btc_close']:,.0f}" if result['btc_close'] else "n/a"

    return f"""<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#2c3e50;padding:24px;background:#f4f6f8">
<div style="max-width:680px;margin:0 auto;background:white;border-radius:12px;padding:24px">
  <h2 style="margin:0">BTC Composite — {result['date']}</h2>
  <p style="color:#7f8c8d;margin:4px 0 20px">BTC close: {btc}</p>

  <div style="background:{sig_color};color:white;padding:16px;border-radius:8px;margin-bottom:20px">
    <div style="font-size:0.9em;opacity:0.85">Signal</div>
    <div style="font-size:1.6em;font-weight:600">{result['signal']}</div>
    <div style="margin-top:8px">Composite score: <strong>{result['composite_score']}/100</strong> · Target BTC esposizione: <strong>{result['target_btc_exposure_pct']}%</strong></div>
  </div>

  <p style="color:#555">{SIGNAL_DESCRIPTIONS.get(result['signal'], '')}</p>

  <table style="width:100%;border-collapse:collapse;margin-top:16px;font-size:0.92em">
    <thead><tr style="background:#ecf0f1">
      <th style="padding:8px 12px;text-align:left">Indicatore</th>
      <th style="padding:8px 12px;text-align:right">Valore</th>
      <th style="padding:8px 12px;text-align:right">Score</th>
      <th style="padding:8px 12px;text-align:left">Zone</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  <div style="background:#fef9e7;border-left:3px solid #f1c40f;padding:12px 16px;border-radius:4px;margin-top:24px;color:#7d6608;font-size:0.85em">
    Non è investment advice. Strumento probabilistico basato su confluenza di indicatori storici. L'era post-ETF potrebbe alterare i pattern.
  </div>
</div></body></html>"""
