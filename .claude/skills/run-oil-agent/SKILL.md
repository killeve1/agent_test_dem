---
name: run-oil-agent
description: Use when asked to run, trigger, or test one decision cycle of the oil-news-agent locally — e.g. "run the agent", "trigger a cycle", "test my change to agent.py/tools.py/thesis.py"
---

# Run Oil Agent Cycle

## Overview

Runs one live decision cycle of the oil-news trading agent locally (same
entrypoint GitHub Actions uses on its schedule), so you can test code changes
or see a fresh decision without waiting for the next scheduled run.

## Prerequisites

- Dependencies installed: `pip install -r requirements.txt`
- At least one provider key exported: `GEMINI_API_KEY` (preferred, falls back
  to Groq automatically) and/or `GROQ_API_KEY`. Check `src/config.py` for how
  provider selection works. Never print or log the key values themselves.

## Usage

Run from the repo root:

```bash
GEMINI_API_KEY=... GROQ_API_KEY=... python src/agent.py
```

Or, if the keys are already exported in the shell:

```bash
python src/agent.py
```

This performs one full cycle: hard-stop-loss check, LLM research/decision loop,
`execute_mock_trade`, and appends a record to `data/decision_log.jsonl`. It
also mutates `data/ledger.json`, `data/active_thesis.json`, and
`data/seen_headlines.json` — treat a local run like a real cycle, not a dry run.

## After Running

Use the `check-oil-status` skill (`python .claude/skills/check-oil-status/status.py 1`)
to see what the cycle just decided, rather than re-parsing raw JSON by hand.

## Common Mistakes

- Forgetting this mutates real local state (ledger, thesis, seen-headlines) —
  data paths are resolved relative to `src/config.py`'s location (always the
  real `data/` dir, regardless of cwd), so a local run updates the same state
  the GitHub Actions schedule uses. If you just want to inspect current state
  without running a cycle, use `check-oil-status` instead.
