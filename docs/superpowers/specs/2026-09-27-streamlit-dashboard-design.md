# Oil News Agent — Streamlit Monitoring Dashboard

**Date:** 2026-09-27
**Status:** Approved for implementation planning

## 1. Purpose

Give a read-only, at-a-glance view of the mock oil-trading agent's current
state and recent behavior: what news it's reading, what it decided, how the
portfolio is doing, and whether its stated confidence is meaningful. Deployed
on Streamlit Community Cloud so it's reachable from a browser without a local
Python setup.

Out of scope: triggering agent cycles from the UI, editing ledger/thesis
state, authentication, or any write path. This is purely a viewer over data
the existing `src/agent.py` cycle already produces.

## 2. Architecture

- **Single file:** `streamlit_app.py` at repo root — Streamlit Community
  Cloud's default entrypoint convention.
- **Data source:** reads `data/ledger.json`, `data/active_thesis.json`, and
  `data/decision_log.jsonl` directly from the deployed repo checkout. No
  database, no API layer — the files GitHub Actions already commits every
  ~10 minutes are the only source of truth.
- **Reused logic:** the loading/parsing helpers in
  `.claude/skills/check-oil-status/status.py` establish the read patterns
  (ledger/thesis/decision-log parsing); `streamlit_app.py` will use the same
  shape of loader functions rather than re-deriving them, but structured for
  Streamlit rendering instead of terminal printing.
- **Freshness caveat:** Streamlit Cloud redeploys/restarts on push to the
  tracked branch. Data is only as fresh as the last GitHub Actions commit
  that Streamlit has picked up — acceptable given the agent's own 10-minute
  cadence. `st.cache_data(ttl=60)` (or similar) is used on the load
  functions so a single Streamlit process doesn't serve stale in-memory data
  between reruns within its own lifetime, but this cannot make data fresher
  than the last deployed commit.
- **No history assumption:** every section is designed to render sensibly
  from zero or one data points, not just from a rich backlog. Empty/sparse
  states (flat with no thesis, zero closed trades, a single decision-log
  entry) are first-class, not error states.

## 3. Components / Sections

Rendered top-to-bottom on a single page (no multi-page nav — the data
doesn't warrant it yet):

### 3.1 Last headline that triggered action
Finds the most recent `decision_log.jsonl` entry whose
`final_trade.arguments.action` is `open_long`, `add`, or `close` (skips
`hold` cycles). Collects every headline returned by that cycle's
`get_recent_news` / `search_news` tool calls, scores each by lowercase
keyword-token overlap against the trade's `reasoning` text, and displays the
top-scoring headline (title as a link, source, published time) labeled
explicitly as a **best-guess match** — the data has no recorded
headline-to-decision citation, so the heuristic is disclosed, not hidden.
Full reasoning text shown alongside for the reader to judge the match
themselves. If no non-hold action exists yet, shows "No action taken yet —
still flat."

### 3.2 KPI header row
Equity (cash + margin + unrealized P&L), current position (contracts @ avg
entry), unrealized P&L, all-time realized P&L, today's P&L % (vs.
`day_start_equity`), and a daily-loss-halt status badge.

### 3.3 Equity curve
Each cycle's `get_portfolio_state` tool-call result in `decision_log.jsonl`
already carries a computed `equity` field (cash + margin + unrealized P&L at
that moment). Walking the log in order and plotting `(timestamp, equity)`
for every cycle that called `get_portfolio_state` gives the curve directly —
no re-derivation needed. Cycles that never called that tool (rare — the
model isn't forced to) are simply skipped as points. With only one or a few
cycles logged, this is just a short line — no special-cased "waiting for
data" placeholder needed.

### 3.4 Trade log + action distribution
Table of `ledger.json`'s `trades[]` (timestamp, action, quantity, price,
confidence, reasoning) and a bar chart of action counts (`hold` /
`open_long` / `add` / `close`).

### 3.5 Active thesis panel
Catalyst, invalidation criteria, monitoring horizon, entry price/time, and
the note history from `active_thesis.json`. Renders "Flat — no active
thesis" when `active` is false, which is expected to be the common state.

### 3.6 Risk / limits panel
Hard-stop-loss threshold vs. current unrealized loss %, max position
contracts vs. current usage, margin utilization, and daily circuit-breaker
status — a "how much room is left" view sourced from `src/config.py`
constants plus current ledger state.

### 3.7 Calibration (confidence vs. outcome)
Win rate and average P&L bucketed by confidence, from
`data/calibration_log.jsonl` (written on position close — same source
`src/calibration.py` already reports on). Expected to show "not enough
closed trades yet (need ~20+ for meaningful stats)" for a long stretch,
since a closed trade requires the agent to have exited a position at least
once. This is a designed-for default state, not an edge case to special-case
later.

## 4. Data Flow

1. On each Streamlit rerun (page load, or a viewer-triggered refresh):
   loader functions read the three/four JSON(L) files from `data/`.
2. Each section's render function receives already-parsed Python
   structures (no section re-parses raw files itself).
3. No writes anywhere in this app — every loader opens files read-only.

## 5. Error Handling

- Missing file (e.g. `calibration_log.jsonl` doesn't exist yet because no
  trade has closed): loader returns an empty list/`None`, and the section
  renders its designed empty state rather than raising.
- Malformed/partial JSONL line (e.g. a truncated write mid-cycle): skip that
  line, don't crash the whole page — surface a small `st.caption` warning
  with a count of skipped lines if any occurred.
- No network calls are made from the dashboard itself, so there's no
  timeout/retry surface to handle.

## 6. Testing

- Manual verification against the current repo's real `data/` files
  (already contains ~50+ hold cycles, zero closed trades, zero active
  thesis) — this exercises the "sparse/empty" states directly, since that's
  the actual current state of the data.
- A short manual check with a hand-crafted fixture data directory
  (temporary copies of `ledger.json`/`decision_log.jsonl` with a fabricated
  `open_long` and `close` pair) to confirm the non-empty-state rendering
  (equity curve with a real swing, calibration bucket appearing, headline
  best-guess-match panel triggering) works before considering the feature
  done. This fixture is throwaway — not committed.
- No automated test suite is being introduced for this — it's a single
  read-only visualization script over already-tested data producers
  (`src/ledger.py`, `src/thesis.py`, `src/calibration.py` own their
  correctness). Streamlit apps are also awkward to unit test meaningfully;
  manual verification against real + fixture data is the appropriate bar
  here.

## 7. Dependencies

Adds `streamlit` (and a charting approach — plain `st.line_chart`/
`st.bar_chart` on pandas DataFrames is sufficient; no need for
plotly/altair given the simplicity of these charts) to `requirements.txt`.
