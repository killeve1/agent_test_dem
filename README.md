# Oil News Agent (Mock Fund)

An agent that monitors oil-market news and decides — on its own, via
tool-calling — whether to open, add to, hold, or close a **long** position
in crude oil futures. Every trade is simulated against a JSON ledger.
**No real money or real exchange is ever involved.**

## How it's "agentic"

This isn't a fixed pipeline (fetch → score → fixed rule → trade). Each
cycle, the LLM (Google Gemini, with automatic fallback to Groq) is given
tools and decides for itself:

- whether it needs more news, a full article, or a targeted search before deciding
- whether current price and recent price history matter enough to check
- whether its open position — and the thesis behind it — still holds
- what action to take, and why

It must always end a cycle by explicitly calling `execute_mock_trade`,
even if the decision is "hold" — so every cycle is logged and auditable.

### Tools available to the agent

| Tool | Purpose |
|---|---|
| `get_recent_news` | Unseen oil-relevant headlines (keyword feeds + LLM-triaged general news) |
| `read_full_article` | Scrape the full text of an article by URL |
| `search_news` | Search for confirmations, official statements, resolution status |
| `get_current_price` | Latest price of the crude futures contract |
| `get_price_history` | Recent OHLCV candles, period high/low and % change (default `1d` / `15m`) — was the headline already priced in? |
| `get_portfolio_state` | Cash, margin, position, P&L, halts, and the active thesis |
| `execute_mock_trade` | `open_long` / `add` / `close` / `hold`, with confidence and thesis fields |

## Persistent working memory: the active thesis

Each cycle is a separate process, so without memory the agent would see
`position_contracts: 1` with no idea why it bought. To fix this, opening a
position from flat **requires** a thesis, stored in `data/active_thesis.json`:

- **`catalyst`** — the specific disruption or event driving the trade
- **`invalidation_criteria`** — the event or price action that proves it wrong
  (e.g. "OPEC raises quotas" or "WTI closes below $95")
- **`monitoring_horizon`** — upcoming events the agent is waiting on
- **`notes`** — a rolling log of per-cycle verdicts (`thesis_note`)

While a position is open, every cycle starts by handing the agent its stored
thesis and asking it to re-validate it first. `add`/`hold` can refine the
thesis or append a note; `close` clears it and copies it into the trade record.
Because clearing happens inside the ledger, a forced hard-stop exit clears
it too.

## Risk controls (deterministic, not LLM-decided)

- **Position sizing** — the model supplies a confidence score; contract count
  is computed from confidence, ATR volatility and a fixed risk budget.
- **Minimum confidence** to act; below it the agent must hold.
- **3% hard stop-loss** — checked before the model is called; force-closes the position.
- **5% daily loss circuit breaker** — blocks new open/add trades for the day.
- **Cooldown** between trades.

## Project structure

```
src/
  config.py       # all tunable constants (symbols, feeds, keywords, risk limits, paths)
  news.py         # two-lane RSS ingestion, article scraping, search, de-duplication
  relevance.py    # batched LLM triage of general-news feeds (fails closed)
  market.py       # live price, ATR volatility, and price history via yfinance
  risk.py         # position sizing, hard stop-loss, daily loss limit
  ledger.py       # mock fund state: cash, margin, position, P&L, trades
  thesis.py       # persistent active investment thesis (working memory)
  tools.py        # tool schemas + dispatcher the agent calls
  agent.py        # the agent loop itself (entry point), Gemini + Groq
  calibration.py  # win rate / P&L by stated confidence — is confidence predictive?
data/
  ledger.json            # current mock fund state (committed each run)
  active_thesis.json     # thesis behind the open position (committed each run)
  seen_headlines.json    # de-dupe memory so old news isn't re-acted on
  decision_log.jsonl     # append-only audit log of every cycle
  calibration_log.jsonl  # one record per closed position
.github/workflows/
  run_agent.yml   # scheduled GitHub Actions run, free, no server needed
```

## Running locally

```bash
pip install -r requirements.txt
export GROQ_API_KEY=...        # required (fallback + relevance triage)
export GEMINI_API_KEY=...      # optional; if set, Gemini is the default provider (override with LLM_PROVIDER=groq)
python src/agent.py            # one decision cycle
python src/calibration.py      # confidence calibration report
```

## Viewing the dashboard

Run `streamlit run streamlit_app.py` locally to visualize the mock fund's equity curve, active trades, historical calibration, and action distribution. The dashboard reads from `data/` (ledger, decisions, and thesis). A read-only public instance is deployed on Streamlit Community Cloud and pointed at this repo's latest data.
