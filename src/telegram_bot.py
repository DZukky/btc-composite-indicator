"""Telegram bot: invia il riepilogo giornaliero come messaggio HTML.

Env vars:
    TELEGRAM_BOT_TOKEN  → ottenuto da @BotFather su Telegram
    TELEGRAM_CHAT_ID    → ID della tua chat con il bot (numero, può essere negativo per gruppi)
    DASHBOARD_URL       → opzionale, link cliccabile alla dashboard pubblica
"""
from __future__ import annotations

import os
import requests

from .config import DCA_BASE_AMOUNT


SIGNAL_EMOJI = {
    "STRONG_SELL": "🔴",
    "DERISK":      "🟠",
    "HOLD":        "⚪",
    "ACCUMULATE":  "🌱",
    "STRONG_BUY":  "💚",
}

# Intensità di acquisto (modello puro accumulo, mai vendere)
SIGNAL_LABEL_IT = {
    "STRONG_SELL": "COMPRA AL MINIMO",
    "DERISK":      "COMPRA DI MENO",
    "HOLD":        "COMPRA NORMALE",
    "ACCUMULATE":  "COMPRA DI PIÙ",
    "STRONG_BUY":  "COMPRA AL MASSIMO",
}

SIGNAL_ACTION_IT = {
    "STRONG_SELL": "BTC è molto caro: compra il minimo (o fermati) e accantona. Niente vendite — i ribassi serviranno per ricomprare più giù.",
    "DERISK":      "BTC è caretto: rallenta gli acquisti e metti da parte la differenza per i giorni migliori.",
    "HOLD":        "Mercato in equilibrio: compra la tua cifra abituale, senza forzare.",
    "ACCUMULATE":  "Zona favorevole: compra più della tua cifra abituale, con calma.",
    "STRONG_BUY":  "Livelli storicamente molto convenienti: compra in modo deciso.",
}


DCA_EMOJI = {"SOSTENUTO": "🟢", "DI ROUTINE": "🔵", "RIDOTTO": "🟠"}

IND_LABEL = {
    "pi_cycle": "Pi Cycle", "mvrv_z": "MVRV Z-Score", "mayer": "Mayer Multiple",
    "two_year_ma": "Media a 2 anni", "rsi_weekly": "RSI settimanale", "nupl": "NUPL",
    "puell": "Puell Multiple", "hash_ribbons": "Hash Ribbons", "bmsb": "Bull Market Band",
}

# Pillole psicologiche a rotazione (una al giorno, per day-of-year)
PILLOLE = [
    "Buy the rumor, sell the news: quando una notizia è su tutti i giornali, spesso il movimento di prezzo è già avvenuto.",
    "Il DCA premia la costanza, non il tempismo perfetto. Comprare un po' a intervalli regolari batte l'attesa del 'momento giusto'.",
    "«Il mercato trasferisce denaro dagli impazienti ai pazienti.» — i bottom si costruiscono nella noia, non nell'euforia.",
    "Sii prudente quando gli altri sono avidi, e sereno quando gli altri hanno paura. Il sentiment estremo è spesso un controindicatore.",
    "Non esiste il prezzo d'ingresso perfetto. Esiste solo il piano che riesci a rispettare con disciplina nel tempo.",
    "La volatilità non è il rischio: il vero rischio è farsi guidare dall'emozione e rompere il proprio piano.",
]


def _pillola() -> str:
    from datetime import date
    return PILLOLE[date.today().timetuple().tm_yday % len(PILLOLE)]


def _curiosity(result: dict) -> str:
    """Gancio di curiosità VERO e dinamico, basato sui dati del giorno."""
    div = result.get("last_divergence")
    if div == "bull":
        return ("👀 Una <b>divergenza RSI rialzista</b> si è accesa di recente: il prezzo ha fatto un nuovo "
                "minimo ma l'RSI no. Storicamente è un segnale di possibile inversione al rialzo.")
    if div == "bear":
        return ("👀 Attenzione: una <b>divergenza RSI ribassista</b> si è accesa di recente. Vale la pena "
                "vedere cosa significa per le prossime settimane.")
    # indicatore più vicino a cambiare zona
    boundaries = [20, 35, 65, 80]
    best = None
    for name, info in result.get("indicators", {}).items():
        s = info.get("score")
        if s is None:
            continue
        dist = min(abs(s - b) for b in boundaries)
        if best is None or dist < best[0]:
            best = (dist, name)
    if best and best[0] <= 6:
        return (f"👀 Occhio al <b>{IND_LABEL.get(best[1], best[1])}</b>: è a un passo dal cambiare valutazione. "
                "Potrebbe muovere il punteggio nei prossimi giorni.")
    return ("🔍 Oggi il quadro è stabile — e a volte la mossa migliore è proprio non fare nulla. "
            "Ma il dettaglio dei 9 indicatori vale comunque un'occhiata.")


def format_message(result: dict, dashboard_url: str | None = None) -> str:
    btc = f"${result['btc_close']:,.0f}" if result["btc_close"] else "n/a"
    regime = "♉️ Bull Market" if result.get("regime", "BULL") == "BULL" else "🐻 Bear Market"
    if result.get("regime_correction"):
        regime += " (in correzione)"

    dca = result.get("dca") or {}
    dca_level = dca.get("level", "DI ROUTINE")
    dca_em = DCA_EMOJI.get(dca_level, "🔵")
    action = SIGNAL_ACTION_IT.get(result["signal"], "")

    # Modello a flusso: moltiplicatore sull'importo di acquisto abituale + salvadanaio
    mult = float(result.get("dca_multiplier", 1.0))
    buy = float(result.get("dca_buy_factor", mult))
    amount = round(DCA_BASE_AMOUNT * buy)
    reserve = float(result.get("reserve_balance", 0.0))
    reserve_line = ""
    if reserve >= 0.05:
        reserve_line = (f"🐷 Salvadanaio: hai messo da parte <b>{reserve:.1f}×</b> la cifra base "
                        f"per i giorni più convenienti.\n")

    msg = (
        f"<b>☕️ Caffè BTC — {result['date']}</b>\n"
        f"💵 Prezzo: <b>{btc}</b>  |  {regime}\n"
        f"\n"
        f"🎯 <b>IL FOCUS DEL GIORNO</b>\n"
        f"{action}\n"
        f"👉 Oggi compra ≈ <b>{buy:.2f}×</b> la tua cifra abituale "
        f"<i>(es. €{DCA_BASE_AMOUNT} → ~€{amount})</i>.\n"
        f"{reserve_line}"
        f"\n"
        f"📊 <b>COSA SUCCEDE DIETRO LE QUINTE?</b>\n"
        f"Score strategico: <b>{result['composite_score']}/100</b> "
        f"(più è basso, più BTC è economico).\n"
        f"🟢 {result.get('fav_count', 0)} favorevoli · ⚪ {result.get('neu_count', 0)} neutri · "
        f"🔴 {result.get('neg_count', 0)} negativi.\n"
        f"{_curiosity(result)}\n"
        f"\n"
        f"⚠️ <b>LA REGOLA DEL MATTINO</b>\n"
        f"<i>{_pillola()}</i>"
    )

    if dashboard_url:
        msg += (
            f"\n\n👇 <b>Vuoi vedere quale indicatore sta guidando la giornata?</b>\n"
            f"La dashboard è aggiornata con grafici e dettagli:\n"
            f"🔍 <a href='{dashboard_url}'>Apri il cruscotto completo</a>"
        )

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


def send_message(text: str, ids_env: str = "TELEGRAM_CHAT_IDS") -> bool:
    """Invia un testo HTML arbitrario (es. alert di rischio) ai chat_id di `ids_env`.

    `ids_env` permette un pubblico diverso dal Caffè (es. RISK_ALERT_CHAT_IDS per
    mandare gli avvisi rischio solo ad alcuni). Fallback a TELEGRAM_CHAT_IDS.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    raw_ids = os.environ.get(ids_env) or os.environ.get("TELEGRAM_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not raw_ids:
        print(f"[telegram] token o {ids_env} non impostati, skip invio")
        return False
    chat_ids = [c.strip() for c in raw_ids.split(",") if c.strip()]
    ok = True
    for chat_id in chat_ids:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=20,
        )
        if r.status_code >= 300:
            print(f"[telegram] errore invio a {chat_id}: {r.status_code} {r.text[:200]}")
            ok = False
        else:
            print(f"[telegram] alert inviato a chat {chat_id}")
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
