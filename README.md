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
