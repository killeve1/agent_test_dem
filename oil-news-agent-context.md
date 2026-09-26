# Oil News Trading Agent — Project Context Export

This document is a handoff summary of an ongoing project, written so another
AI assistant (or a future session) can understand the current state, the
design decisions already made and why, and what's still open — without
re-deriving everything from scratch.

**Pair this doc with the actual project source** (a zip of the `oil-news-agent`
folder) if you want the receiving AI to read/edit real code rather than just
understand the architecture.

---

## 1. What this is

An agentic system that monitors oil-market news and autonomously decides
whether to open, add to, hold, or close a **long-only** position in crude
oil futures, against a **mock/paper fund only** — no real money or real
exchange involved anywhere. Built and iterated with Claude over an extended
session; deployed and currently running live on GitHub Actions.

**Owner context**: Smedley (Siddhant Jain), MBA student (Digital Enterprise
Management) at IIM Udaipur. Building this as a personal/learning project,
cost-sensitive (explicitly wants free infra throughout), comfortable with
Python, Node.js/Postgres background, works on a Mac.

## 2. Why it's "agentic" and not a pipeline

Early design discussion explicitly distinguished a fixed pipeline (fetch →
score → fixed-rule → trade) from a real agent (model decides what
information it needs and what to do with tool access). The system was
deliberately built as the latter: the LLM is given tools and decides for
itself how many times to check news, whether to check price/portfolio
state, and what final action to take — it isn't sequenced by hardcoded
Python logic.

## 3. Current architecture

```
src/
  config.py      # all tunable constants — read this first, it's the map of the whole system
  news.py        # two-lane headline fetching (see §5)
  relevance.py   # batched LLM triage for the "general" news lane
  market.py      # live price + ATR (volatility) via yfinance
  ledger.py      # mock fund state, margin accounting, sizing, daily-loss tracking
  risk.py        # deterministic position sizing + hard-stop + daily circuit breaker
  tools.py       # tool schemas (OpenAI/Groq-compatible) + dispatcher
  agent.py       # the main agent loop (entry point), pre-LLM hard-stop check
  calibration.py # standalone script: is stated confidence actually predictive?
data/
  ledger.json            # current fund state, committed back to repo each run
  seen_headlines.json    # dedup memory across both news lanes
  decision_log.jsonl     # full audit trail of every cycle's tool calls + reasoning
  calibration_log.jsonl  # closed-trade outcomes tagged with confidence, for calibration
.github/workflows/
  run_agent.yml  # scheduled trigger (see §7 — currently unreliable) + workflow_dispatch
```

## 4. LLM provider setup

- **Groq** (OpenAI-compatible API) is the current single provider for
  everything: `openai/gpt-oss-120b` for the main trading decision loop,
  `openai/gpt-oss-20b` for the cheap relevance-triage batch call.
- Groq deprecated `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` on
  2026-08-16; the project already migrated off both to the `gpt-oss` family.
  **Groq's model lineup churns fast — always verify current model names
  against `console.groq.com/docs/deprecations` before assuming a name is
  still valid.**
- **In-progress design discussion (not yet built)**: splitting providers —
  Gemini as the trading decision-maker, Groq kept as-is for relevance
  triage. This requires a real rewrite of `agent.py` (Gemini's function-
  calling API shape differs from OpenAI/Groq's — different message/content
  structure, different response parsing), but `tools.py`'s dispatcher and
  all the actual tool implementations are provider-agnostic already and
  need zero changes. `relevance.py` is already fully independent of
  `agent.py` and would need no changes either way.

## 5. News ingestion — two-lane design

This was a deliberate fix for a real gap discovered mid-project: a keyword-
only filter will always miss stories that are genuinely oil-relevant but
never use oil vocabulary (a real example that was caught live: Saudi
Arabia's East-West Pipeline shutdown, reported with zero mentions of "oil"
in the immediate headline).

- **Lane 1 — `RSS_FEEDS`** (OilPrice, EIA, Investing.com commodities):
  filtered by a cheap `OIL_KEYWORDS` substring match. Trusted directly, no
  LLM call needed, near-zero cost.
- **Lane 2 — `GENERAL_NEWS_FEEDS`** (currently BBC Middle East RSS):
  **unfiltered** — every entry is a candidate. A single **batched** Groq
  call (`relevance.classify_batch`) judges all of that cycle's new
  candidates at once (not one call per headline — this keeps API usage
  trivial regardless of feed volume). Fails **closed**: any classification
  error drops all candidates from that lane rather than risking unfiltered
  noise reaching the trading agent.
- Both lanes dedup through the same `seen_headlines.json` hash set, so nothing
  is classified or reacted to twice.

## 6. Mock fund accounting — margin-based, not notional

**Bug already found and fixed**: the first version deducted full notional
value (price × 1,000 barrels) from cash on every trade, as if buying the
barrels outright — this is wrong for futures and caused cash to go
deeply negative on a 2-contract trade. Fixed to a proper margin model:

- `MARGIN_PER_CONTRACT` (currently $6,800, approximating CME WTI initial
  margin — this moves with volatility in reality and is a rough constant)
  is what actually gets deducted from cash into `margin_held` on open/add.
- On close: margin is returned to cash, realized P&L settles in cash.
- `get_portfolio_state` reports `cash_available`, `margin_held`, and total
  `equity` (cash + margin + unrealized P&L) as distinct figures.

## 7. Position sizing — confidence + volatility driven, not flat

**Also already built, per explicit design request** ("how much to trade,
not just what"): the model does **not** choose a contract quantity. It
supplies a `confidence` score (0–1) via the `execute_mock_trade` tool;
actual size is computed deterministically in `risk.compute_position_size`:

```
risk_dollars       = equity × BASE_RISK_PCT × confidence
stop_distance       = ATR × STOP_LOSS_ATR_MULTIPLIER
risk_per_contract   = stop_distance × CONTRACT_MULTIPLIER
quantity            = floor(risk_dollars / risk_per_contract), capped by MAX_POSITION_CONTRACTS
```

**Known constant-tuning issue already resolved once**: at the initial
`BASE_RISK_PCT = 0.02`, sizing came back 0 contracts even at 0.8 confidence
under normal volatility — a real mismatch between a $100k mock account and
one full WTI contract's size (1,000 barrels, ~$100k+ notional). Bumped to
`0.04`. Sizing correctly returning 0 during a genuine volatility spike is
**intentional risk-off behavior, not a bug** — this distinction has come up
more than once and is worth preserving in any explanation of the system.

An unexplored but discussed alternative: switch to CME Micro WTI (100
barrels/contract, 1/10 size) for finer-grained sizing at this account scale.

## 8. Risk controls — enforced in code, never by the model

Two circuit breakers, both deliberately kept outside the LLM's control:

- **Hard stop-loss** (`HARD_STOP_LOSS_PCT`, 3%): checked in `agent.py`
  **before the model is even called** each cycle. If breached, the position
  is force-closed directly against the ledger and the cycle ends — the
  model never gets a vote.
- **Daily loss circuit breaker** (`MAX_DAILY_LOSS_PCT`, 5%): enforced
  *inside* `ledger.execute_mock_trade` itself (not just upstream in the
  agent loop), so no caller can bypass it by skipping a check. Tracks a
  per-day equity baseline that resets on date rollover (IST).

## 9. Calibration — is "confidence" meaningful?

Every closed trade logs `{avg_confidence, realized_pnl, won}` to
`calibration_log.jsonl`. `calibration.py` buckets closed trades by
confidence range and reports win rate / avg P&L per bucket — the explicit
purpose is to eventually check whether the model's stated confidence
actually predicts outcomes, or whether it's decorative. **Not enough closed
trades exist yet to draw any real conclusion** — this needs to run for a
meaningful stretch before the numbers mean anything.

## 10. Deliberately out of scope so far

- **Backtesting** the news→price-direction thesis against historical data —
  explicitly declined by the user ("i dont want to build 4" — referring to
  a numbered list where backtesting was #4). This means the sizing/risk
  layers are built on an unvalidated hypothesis; worth flagging if asked to
  extend or trust this system further.
- **Shorting** — long-only by explicit design.
- **Truth Social / OSINT account monitoring** — discussed at length but not
  built. Key finding: no public self-serve Truth Social API exists (an
  institutional "Truth API" launched ~July 2026 at $60–100k/month is not
  viable for this project); third-party scrapers exist for a handful of
  top accounts but carry real ToS risk and could be closed off anytime.
  If revisited, the same two-lane pattern from §5 (broad unfiltered source
  + batched relevance classifier) is the natural extension point.

## 11. Deployment status — known infrastructure issue

Deployed on **GitHub Actions**, chosen specifically for being free with no
server to maintain. Workflow commits `data/` back to the repo every run,
making Git history a full audit trail.

**Known unresolved problem**: GitHub's native `schedule:` cron trigger is
unreliable at sub-hourly intervals — observed empirically as 7 actual runs
across ~16.5 hours against an expected ~99 at a 10-minute cron. This
matches a documented GitHub-side regression traced to an outage around
2026-08-26/27; `workflow_dispatch` (manual/API-triggered) runs remain
reliable throughout, only the internal scheduler is affected. **User has
chosen to fix this via an external trigger** (a Cloudflare Worker Cron
Trigger calling the GitHub REST API's `workflow_dispatch` endpoint on a
real schedule) rather than tolerating the gaps or moving to an always-on
VM — **this Cloudflare Worker setup was the very next step being discussed
before this export was requested, and has not yet been built.**

## 12. Other resolved issues worth knowing about (avoid re-litigating)

- All timestamps use a fixed IST offset (`+05:30`), not UTC — explicit user
  request, implemented via a fixed `timezone(timedelta(hours=5, minutes=30))`
  in `config.py`, not `zoneinfo` (avoids a tzdata dependency).
- `pip install -r requirements.txt` works correctly as authored — an earlier
  "won't work" report couldn't be reproduced in a clean venv; likely an
  environment-specific issue on the user's Mac (never fully diagnosed,
  possibly a PEP 668 externally-managed-environment error) rather than a
  requirements-file problem.
- Two separate GitHub Actions secrets-vs-environments confusions were
  resolved: use **repository secrets**, not environment secrets — the
  workflow YAML has no `environment:` key, so environment-scoped secrets
  would be invisible to it.

## 13. Immediate next step (in progress when this was exported)

Build the Cloudflare Worker external-trigger setup described in §11, to
work around GitHub's unreliable native scheduler while keeping the rest of
the GitHub Actions-based deployment unchanged.

## 14. Longer-term open threads

- Gemini-as-decision-maker / Groq-as-triage provider split (§4) — designed,
  not built. Rationale given: separate providers roughly double effective
  free-tier daily capacity if Groq's limits ever become binding, plus
  provider redundancy.
- A Streamlit dashboard reading `ledger.json` / `decision_log.jsonl` /
  `calibration_log.jsonl` — architecture discussed (equity curve, trade
  log, calibration chart, live state header) but explicitly not yet built
  ("just how we will build it" — planning only so far). Open question
  flagged but not resolved: reading a **private** GitHub repo's data files
  requires a GitHub PAT with read-only Contents access, stored in
  Streamlit Community Cloud's secrets manager — versus the simpler
  alternative of a public repo needing no auth at all.
- Backtesting the core news→direction thesis remains the single biggest
  unvalidated assumption underlying the whole sizing/risk system (§10).
