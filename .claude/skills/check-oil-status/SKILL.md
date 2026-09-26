---
name: check-oil-status
description: Use when asked about the oil-news-agent's current position, P&L, active thesis, or recent trade decisions — e.g. "what's the portfolio look like", "are we long oil right now", "why did it hold last cycle"
---

# Check Oil Agent Status

## Overview

Reads `data/ledger.json`, `data/active_thesis.json`, and `data/decision_log.jsonl`
directly and prints a formatted summary: cash, position, P&L, the active thesis
(catalyst/invalidation/monitoring horizon), and the last N decision cycles with
their reasoning. No API keys or network calls required.

## When to Use

- "What's our current oil position?"
- "Is there an active thesis right now?"
- "What did the agent decide the last few cycles?"
- Sanity-checking `data/` state before or after debugging `src/ledger.py`,
  `src/thesis.py`, or `src/agent.py`

## Usage

```bash
python .claude/skills/check-oil-status/status.py       # last 3 cycles (default)
python .claude/skills/check-oil-status/status.py 10     # last 10 cycles
```

Run from the repo root (or any cwd — the script resolves `data/` relative to
its own location, not the cwd).

## Output

Three sections: `Portfolio` (cash, contracts, avg entry, margin, realized P&L,
day-start equity, trade count), `Active Thesis` (or "Flat" if none), and the
last N decision cycles with provider, action, confidence, and a truncated
reasoning string.
