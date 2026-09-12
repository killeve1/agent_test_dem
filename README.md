# Oil News Agent (Mock Fund)

An agent that monitors oil-market news and decides — on its own, via
tool-calling — whether to open, add to, hold, or close a **long** position
in crude oil futures. Every trade is simulated against a JSON ledger.
**No real money or real exchange is ever involved.**

## How it's "agentic"

This isn't a fixed pipeline (fetch → score → fixed rule → trade). Each
cycle, the LLM (via Groq) is given tools and decides for itself:

- whether it needs more news before deciding
- whether current price context matters enough to check
- whether its own current position changes what it should do
- what action to take, and why

It must always end a cycle by explicitly calling `execute_mock_trade`,
even if the decision is "hold" — so every cycle is logged and auditable.

## Project structure

```
src/
  config.py    # all tunable constants (symbols, keywords, risk limits)
  news.py      # RSS fetching + oil-relevance filtering + de-duplication
  market.py    # live futures price via yfinance
  ledger.py    # mock fund state: cash, position, avg price, P&L, trades
  tools.py     # tool schemas + dispatcher the agent calls
  agent.py     # the agent loop itself (entry point)
data/
  ledger.json           # current mock fund state (committed each run)
  seen_headlines.json   # de-dupe memory so old news isn't re-acted on
  decision_log.jsonl    # append-only audit log of every cycle
.github/workflows/
  run_agent.yml # scheduled GitHub Actions run, free, no server needed
```

## Setup

1. **Get a free Groq API key**: https://console.groq.com
2. **Fork/push this repo to your own GitHub account.**
3. **Add the key as a repo secret**: repo → Settings → Secrets and
   variables → Actions → New repository secret → name it `GROQ_API_KEY`.
4. That's it — the workflow in `.github/workflows/run_agent.yml` runs
   every 30 minutes automatically and commits the updated ledger back
   to the repo.

## Running locally (for testing/debugging)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export GROQ_API_KEY=your_key_here
cd src
python agent.py
```

Each run is one independent decision cycle — check `data/ledger.json`
afterward to see the resulting position, and `data/decision_log.jsonl`
for the full reasoning trail.

## Tuning it

Everything worth adjusting lives in `src/config.py`:
- `RSS_FEEDS` / `OIL_KEYWORDS` — what counts as relevant news
- `MIN_CONFIDENCE_TO_ACT` — how sure the agent must be before trading
- `MAX_POSITION_CONTRACTS` / `TRADE_SIZE_CONTRACTS` — position sizing
- `COOLDOWN_MINUTES` — minimum gap between trades
- `GROQ_MODEL` — swap in a different Groq-hosted model if you want

## Suggested next steps

- Add a small Streamlit dashboard reading `data/ledger.json` and
  `data/decision_log.jsonl` to visualize P&L and decision history over time.
- Give the agent a `get_price_history` tool so it can reason about
  recent price trend, not just the latest tick.
- Backtest the sentiment/decision logic against historical headlines
  before trusting the live cycle's judgment.
