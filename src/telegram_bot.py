"""Telegram bot: invia il riepilogo giornaliero come messaggio HTML.

Env vars:
    TELEGRAM_BOT_TOKEN  → ottenuto da @BotFather su Telegram
    TELEGRAM_CHAT_ID    → ID della tua chat con il bot (numero, può essere negativo per gruppi)
    DASHBOARD_URL       → opzionale, link cliccabile alla dashboard pubblica
"""
from __future__ import annotations

import os
import requests


SIGNAL_EMOJI = {
    "STRONG_SELL": "🔴",
    "DERISK":      "🟠",
    "HOLD":        "⚪",
    "ACCUMULATE":  "🌱",
    "STRONG_BUY":  "💚",
}

SIGNAL_LABEL_IT = {
    "STRONG_SELL": "ALLEGGERISCI FORTEMENTE",
    "DERISK":      "INIZIA A RIDURRE",
    "HOLD":        "MANTIENI POSIZIONE",
    "ACCUMULATE":  "ACCUMULA",
    "STRONG_BUY":  "OCCASIONE D'INGRESSO",
}

SIGNAL_ACTION_IT = {
    "STRONG_SELL": "Riduci immediatamente l'esposizione BTC. Storicamente seguono drawdown del 50-85%.",
    "DERISK":      "Alleggerisci progressivamente. Più indicatori entrano in zona di surriscaldamento.",
    "HOLD":        "Niente di particolare da fare. Trend follow.",
    "ACCUMULATE":  "Compra gradualmente, niente fretta. Zona favorevole.",
    "STRONG_BUY":  "Momento storicamente favorevole all'accumulo aggressivo.",
}


def _format_value(name: str, v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Sì" if v else "No"
    if name in ("mvrv_z", "rsi_weekly", "puell"):
        return f"{v:.2f}"
    return f"{v:.3f}"


def format_message(result: dict, dashboard_url: str | None = None) -> str:
    emoji = SIGNAL_EMOJI.get(result["signal"], "")
    label = SIGNAL_LABEL_IT.get(result["signal"], result["signal"])
    action = SIGNAL_ACTION_IT.get(result["signal"], "")
    btc = f"${result['btc_close']:,.0f}" if result["btc_close"] else "n/a"

    regime_map = {"BULL": "🟢 Bull market", "BEAR": "🔴 Bear market"}
    regime_line = regime_map.get(result.get("regime", "BULL"), "🟢 Bull market")
    if result.get("regime_correction"):
        regime_line += " (in correzione)"

    div = result.get("last_divergence")
    div_line = ""
    if div == "bull":
        div_line = f"\n📈 <b>Divergenza RSI rialzista</b> ({result.get('last_divergence_age_days','?')}g fa) — possibile inversione su"
    elif div == "bear":
        div_line = f"\n📉 <b>Divergenza RSI ribassista</b> ({result.get('last_divergence_age_days','?')}g fa) — attenzione, possibile inversione giù"

    dca = result.get("dca") or {}
    dca_emoji = {"AGGRESSIVO": "🟢", "REGOLARE": "🔵", "PRUDENTE": "🟠"}.get(dca.get("level"), "🔵")
    dca_line = f"\n💧 DCA: <b>{dca.get('level', 'REGOLARE')}</b> {dca_emoji}" if dca else ""

    msg = (
        f"<b>📅 BTC Composite — {result['date']}</b>\n"
        f"BTC oggi: <b>{btc}</b> · {regime_line}\n\n"
        f"{emoji} <b>{label}</b>\n"
        f"<i>{action}</i>\n\n"
        f"💰 <b>Allocazione BTC suggerita: {result['target_btc_exposure_pct']}%</b>\n"
        f"<i>(della quota cripto che hai già destinato a BTC, non del patrimonio totale)</i>"
        f"{dca_line}\n\n"
        f"📊 Composite score: {result['composite_score']}/100\n"
        f"🟢 Favorevoli: {result['green_count']}/9 · 🔴 Negativi: {result['red_count']}/9"
        f"{div_line}"
    )

    if dashboard_url:
        msg += f"\n\n🔗 <a href='{dashboard_url}'>Vedi dashboard completa</a>"

    return msg


def send(result: dict, dashboard_url: str | None = None) -> bool:
    """Invia il messaggio a uno o più chat_id.

    Env vars:
      TELEGRAM_BOT_TOKEN  → token dal @BotFather
      TELEGRAM_CHAT_IDS   → lista comma-separated di chat_id (es. "12345,67890")
      TELEGRAM_CHAT_ID    → singolo chat_id (legacy, supportato come fallback)
      DASHBOARD_URL       → opzionale, link al dashboard pubblico
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    raw_ids = os.environ.get("TELEGRAM_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID")
    dashboard_url = dashboard_url or os.environ.get("DASHBOARD_URL")

    if not token or not raw_ids:
        print("[telegram] TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_IDS non impostati, skip invio")
        return False

    chat_ids = [c.strip() for c in raw_ids.split(",") if c.strip()]
    text = format_message(result, dashboard_url)
    ok = True
    for chat_id in chat_ids:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if r.status_code >= 300:
            print(f"[telegram] errore invio a {chat_id}: {r.status_code} {r.text[:200]}")
            ok = False
        else:
            print(f"[telegram] inviato a chat {chat_id}")
    return ok


def get_updates_chat_ids(token: str) -> list[dict]:
    """Helper per scoprire il CHAT_ID dopo che l'utente ha scritto al bot.

    Esempio di output: [{"chat_id": 123456789, "name": "Davide", "text": "/start"}, ...]
    """
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    r.raise_for_status()
    data = r.json()
    out = []
    for u in data.get("result", []):
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat", {})
        if "id" in chat:
            out.append({
                "chat_id": chat["id"],
                "name": chat.get("first_name") or chat.get("title") or chat.get("username"),
                "text": msg.get("text", ""),
            })
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "discover":
        token = os.environ.get("TELEGRAM_BOT_TOKEN") or sys.argv[2] if len(sys.argv) > 2 else None
        if not token:
            print("Usage: python -m src.telegram_bot discover <BOT_TOKEN>")
            sys.exit(1)
        chats = get_updates_chat_ids(token)
        if not chats:
            print("Nessun messaggio trovato. Scrivi /start al bot e riprova.")
        else:
            for c in chats:
                print(f"chat_id={c['chat_id']}  name={c['name']}  text={c['text']!r}")
