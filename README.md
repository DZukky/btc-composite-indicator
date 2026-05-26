# BTC Composite Indicator

**Dashboard live**: https://dzukky.github.io/btc-composite-indicator/

Strumento giornaliero di segnali reversal per Bitcoin: combina 9 indicatori storicamente correlati con top/bottom di ciclo in un singolo composite score 0–100, con position sizing operativo e alert Telegram giornalieri.

**Non è investment advice.** Sample size storico: 3–4 cicli completi. L'era post-ETF (2024+) potrebbe alterare i pattern.

## Cosa fa

1. **Fetch** dati da fonti gratuite ogni mattina:
   - Binance public API → prezzo BTCUSDT daily (dal 2017)
   - bitcoin-data.com → MVRV Z-Score, NUPL, Puell Multiple, RHODL
   - Blockchain.info → hash rate

2. **Calcola** 9 indicatori:

   | Indicatore | Peso | Top trigger | Bottom trigger |
   |---|---:|---|---|
   | Pi Cycle Top (111DMA / 350DMA×2) | 15% | ≥0.95 | — |
   | MVRV Z-Score | 18% | >6 | <0 |
   | Mayer Multiple (price / 200DMA) | 12% | >2.4 | <1.0 |
   | 2-Year MA Multiplier | 10% | >4 | <1 |
   | RSI Weekly | 10% | >85 | <35 |
   | NUPL | 10% | >0.70 | <0 |
   | Puell Multiple | 10% | >3.5 | <0.5 |
   | Hash Ribbons | 8% | — | Buy cross post-capitulation |
   | Bull Market Support Band | 7% | >1.30 ext | <1 (sotto banda) |

3. **Score composito** = somma pesata, ciascun indicatore normalizzato in score 0–100 lineare tra le soglie storiche.

4. **Signal**:
   - `STRONG_SELL` se score ≥80 e ≥4 indicatori in red zone
   - `DERISK` se score ≥70
   - `HOLD` zona neutra
   - `ACCUMULATE` se score ≤30
   - `STRONG_BUY` se score ≤20 e ≥4 indicatori in green zone

5. **Position sizing** = sigmoide del composite score:
   `target_pct = 100 / (1 + exp((score - 50) / 10))`

6. **Output**: dashboard HTML in `dashboard/index.html` + email automatica via Resend.

## Esecuzione locale

```bash
pip install -r requirements.txt
python -m src.main                 # esegue tutto
python -m src.main --no-fetch      # usa solo cache locale
python -m src.main --no-email      # niente email
open dashboard/index.html
```

## Deploy automatico

Il workflow `.github/workflows/daily.yml` esegue la pipeline ogni mattina alle 06:00 UTC, commita la cache aggiornata e deploya la dashboard su GitHub Pages.

Per attivare l'email, aggiungi i secret nel repo GitHub:
- `RESEND_API_KEY` = la tua API key da resend.com (free tier 3000 email/mese)
- `RESEND_FROM` = es. `BTC Composite <onboarding@resend.dev>` (o un dominio verificato)

## Struttura

```
btc-tool/
├── src/
│   ├── config.py       # pesi, soglie, trigger
│   ├── fetchers.py     # download dati da API free
│   ├── indicators.py   # calcolo dei 9 indicatori
│   ├── composite.py    # scoring + sizing
│   ├── reporter.py     # generatore dashboard HTML + email HTML
│   └── main.py         # orchestrator
├── data/cache/         # CSV di cache (rigenerati incrementalmente)
├── dashboard/index.html
└── .github/workflows/daily.yml
```

## Note sui limiti

- Sample size piccolo: 3 top + 4 bottom completi. Ogni "X% win rate" ha intervallo di confidenza ampio.
- Post-ETF (2024+): il classico schema halving-driven è stato già "rotto" dall'ATH pre-halving del 14 marzo 2024. Bitcoin Magazine Pro avverte che il Pi Cycle potrebbe "cessare di essere rilevante".
- Indicatori on-chain (MVRV/NUPL/Puell) sono **valuation**, non timing: possono restare in red zone per settimane prima del top effettivo.
- Stock-to-Flow di PlanB **non è incluso** (modello disconfermato: deviazione >65% dal target dicembre 2021).
