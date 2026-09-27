# Streamlit Monitoring Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Streamlit dashboard over the oil-news-agent's existing `data/` files (ledger, active thesis, decision log, calibration log), deployable on Streamlit Community Cloud.

**Architecture:** Split into `dashboard_data.py` (pure, dependency-free data loading and derivation functions — fully unit-testable with pytest) and `streamlit_app.py` (thin rendering layer that imports `dashboard_data` and calls `st.*`). This is a deliberate refinement of the spec's "single file" architecture: it keeps every piece of non-trivial logic (equity-curve extraction, KPI math, the headline-matching heuristic, calibration bucketing) behind a TDD cycle, while the genuinely hard-to-unit-test part (Streamlit rendering calls) stays a thin, manually-verified layer, matching the spec's own reasoning in its Testing section. `streamlit_app.py` remains the sole file Streamlit Community Cloud needs as its entrypoint.

**Tech Stack:** Python 3.13, Streamlit, pandas (for `st.line_chart`/`st.bar_chart` inputs), pytest (new dev dependency — no test infrastructure exists in this repo yet).

**Spec:** `docs/superpowers/specs/2026-09-27-streamlit-dashboard-design.md`

## Global Constraints

- Read-only: the dashboard never writes to any file under `data/`.
- No network calls from the dashboard itself (`src/agent.py` and friends already own the live-data fetching; the dashboard only ever reads what they've already written).
- No authentication — this stays a public read-only viewer.
- Streamlit Community Cloud entrypoint is `streamlit_app.py` at the repo root.
- Charting uses plain `st.line_chart` / `st.bar_chart` on pandas DataFrames — no plotly/altair.
- Every section renders a designed empty/sparse state (zero decisions, zero closed trades, no active thesis) rather than raising or showing a blank crash.
- A missing or malformed `data/*.json(l)` file must not crash the page — loaders return `None`/`[]` and callers handle it.

---

## File Structure

- Create: `dashboard_data.py` (repo root) — all loading and derivation logic, no `streamlit` import.
- Create: `streamlit_app.py` (repo root) — the Streamlit entrypoint; imports `dashboard_data`, renders sections in the order from the spec.
- Create: `tests/test_dashboard_data.py` — pytest tests for every function in `dashboard_data.py`.
- Create: `tests/__init__.py` — empty, so pytest can discover the package cleanly.
- Modify: `requirements.txt` — add `streamlit`, `pandas`, `pytest`.

---

### Task 1: Dependencies and project scaffolding

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: an importable `tests` package and the three new dependencies available in the environment for every later task.

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:

```
streamlit>=1.38.0
pandas>=2.2.0
pytest>=8.0.0
```

- [ ] **Step 2: Install and verify**

Run: `pip install -r requirements.txt`
Then: `python3 -c "import streamlit, pandas, pytest; print('ok')"`
Expected: prints `ok` with no import errors.

- [ ] **Step 3: Create the tests package**

Create `tests/__init__.py` with empty content (0 bytes).

- [ ] **Step 4: Commit**

```bash
git add requirements.txt tests/__init__.py
git commit -m "Add streamlit, pandas, pytest dependencies for dashboard"
```

---

### Task 2: Ledger and thesis loaders

**Files:**
- Create: `dashboard_data.py`
- Test: `tests/test_dashboard_data.py`

**Interfaces:**
- Produces:
  - `REPO_ROOT: str`, `DATA_DIR: str`, `LEDGER_PATH: str`, `THESIS_PATH: str`, `DECISION_LOG_PATH: str`, `CALIBRATION_LOG_PATH: str` (module-level constants)
  - `load_ledger(path: str = LEDGER_PATH) -> dict | None`
  - `load_thesis(path: str = THESIS_PATH) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_data.py`:

```python
import json
import dashboard_data as dd


def test_load_ledger_missing_file_returns_none(tmp_path):
    missing = tmp_path / "no_such_ledger.json"
    assert dd.load_ledger(str(missing)) is None


def test_load_ledger_reads_json(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"cash": 100000.0, "trades": []}))
    result = dd.load_ledger(str(path))
    assert result == {"cash": 100000.0, "trades": []}


def test_load_thesis_missing_file_returns_none(tmp_path):
    missing = tmp_path / "no_such_thesis.json"
    assert dd.load_thesis(str(missing)) is None


def test_load_thesis_reads_json(tmp_path):
    path = tmp_path / "active_thesis.json"
    path.write_text(json.dumps({"active": False}))
    result = dd.load_thesis(str(path))
    assert result == {"active": False}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard_data'`

- [ ] **Step 3: Write the minimal implementation**

Create `dashboard_data.py`:

```python
"""Read-only data loading and derivation for the Streamlit dashboard.

No `streamlit` import in this module — everything here is plain Python,
testable with pytest, so the dashboard's non-trivial logic (KPI math,
equity-curve extraction, the headline-matching heuristic, calibration
bucketing) has a real test cycle instead of only manual verification.
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO_ROOT, "data")

LEDGER_PATH = os.path.join(DATA_DIR, "ledger.json")
THESIS_PATH = os.path.join(DATA_DIR, "active_thesis.json")
DECISION_LOG_PATH = os.path.join(DATA_DIR, "decision_log.jsonl")
CALIBRATION_LOG_PATH = os.path.join(DATA_DIR, "calibration_log.jsonl")


def load_ledger(path: str = LEDGER_PATH) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_thesis(path: str = THESIS_PATH) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add ledger and thesis loaders for dashboard"
```

---

### Task 3: Decision log and calibration log loaders (JSONL, skip malformed lines)

**Files:**
- Modify: `dashboard_data.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `load_jsonl(path: str) -> tuple[list[dict], int]` — returns `(records, skipped_count)`; used by `streamlit_app.py` for both `DECISION_LOG_PATH` and `CALIBRATION_LOG_PATH`, and by every later derivation function in this plan (which all take the already-loaded `decisions` list, not a path).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_data.py`:

```python
def test_load_jsonl_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "no_such_log.jsonl"
    records, skipped = dd.load_jsonl(str(missing))
    assert records == []
    assert skipped == 0


def test_load_jsonl_parses_valid_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}\n{"a": 2}\n')
    records, skipped = dd.load_jsonl(str(path))
    assert records == [{"a": 1}, {"a": 2}]
    assert skipped == 0


def test_load_jsonl_skips_malformed_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}\nnot json\n{"a": 2}\n\n')
    records, skipped = dd.load_jsonl(str(path))
    assert records == [{"a": 1}, {"a": 2}]
    assert skipped == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `AttributeError: module 'dashboard_data' has no attribute 'load_jsonl'`

- [ ] **Step 3: Write the minimal implementation**

Append to `dashboard_data.py`:

```python
def load_jsonl(path: str) -> tuple[list[dict], int]:
    if not os.path.exists(path):
        return [], 0
    records = []
    skipped = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                skipped += 1
    return records, skipped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add JSONL loader that skips malformed lines"
```

---

### Task 4: Latest portfolio state and equity curve extraction

**Files:**
- Modify: `dashboard_data.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: a `decisions: list[dict]` in the shape written by `src/agent.py`'s `_log_decision` — each cycle dict has `timestamp: str` and `tool_calls: list[dict]`, where each tool call has `tool: str` and `result: dict`. The `get_portfolio_state` tool's result always has an `equity: float` key, and an `unrealized_pnl: float` key only when a position is open (confirmed against `src/ledger.py:get_portfolio_state` — the key is entirely absent when flat, never `0.0`).
- Produces:
  - `latest_portfolio_state(decisions: list[dict]) -> dict | None` — the most recent cycle's `get_portfolio_state` result dict, or `None` if no cycle ever called it.
  - `get_equity_curve(decisions: list[dict]) -> list[dict]` — `[{"timestamp": str, "equity": float}, ...]` in chronological order, one point per cycle that called `get_portfolio_state`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_data.py`:

```python
def _cycle(timestamp, portfolio_result=None):
    tool_calls = []
    if portfolio_result is not None:
        tool_calls.append({"tool": "get_portfolio_state", "arguments": {}, "result": portfolio_result})
    return {"timestamp": timestamp, "tool_calls": tool_calls}


def test_latest_portfolio_state_returns_none_when_no_cycles_called_it():
    decisions = [_cycle("t1"), _cycle("t2")]
    assert dd.latest_portfolio_state(decisions) is None


def test_latest_portfolio_state_returns_most_recent():
    decisions = [
        _cycle("t1", {"equity": 100000.0}),
        _cycle("t2", {"equity": 100500.0}),
    ]
    assert dd.latest_portfolio_state(decisions) == {"equity": 100500.0}


def test_get_equity_curve_skips_cycles_without_portfolio_state():
    decisions = [
        _cycle("t1", {"equity": 100000.0}),
        _cycle("t2"),
        _cycle("t3", {"equity": 100200.0}),
    ]
    assert dd.get_equity_curve(decisions) == [
        {"timestamp": "t1", "equity": 100000.0},
        {"timestamp": "t3", "equity": 100200.0},
    ]


def test_get_equity_curve_empty_when_no_decisions():
    assert dd.get_equity_curve([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `AttributeError: module 'dashboard_data' has no attribute 'latest_portfolio_state'`

- [ ] **Step 3: Write the minimal implementation**

Append to `dashboard_data.py`:

```python
def latest_portfolio_state(decisions: list[dict]) -> dict | None:
    for cycle in reversed(decisions):
        for call in cycle.get("tool_calls", []):
            if call.get("tool") == "get_portfolio_state":
                return call.get("result")
    return None


def get_equity_curve(decisions: list[dict]) -> list[dict]:
    points = []
    for cycle in decisions:
        for call in cycle.get("tool_calls", []):
            if call.get("tool") == "get_portfolio_state" and "equity" in call.get("result", {}):
                points.append({"timestamp": cycle.get("timestamp"), "equity": call["result"]["equity"]})
                break
    return points
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add equity curve extraction from decision log"
```

---

### Task 5: KPI computation

**Files:**
- Modify: `dashboard_data.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `ledger: dict` (from `load_ledger`, always has `cash`, `position_contracts`, `avg_entry_price`, `realized_pnl`, `day_start_equity`), `decisions: list[dict]`, and `latest_portfolio_state` from Task 4.
- Produces: `compute_kpis(ledger: dict, decisions: list[dict]) -> dict` with keys `equity`, `position_contracts`, `avg_entry_price`, `unrealized_pnl`, `realized_pnl`, `today_pnl_pct`, `daily_loss_halt` (the raw dict, e.g. `{"halted": False}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_data.py`:

```python
def _ledger(**overrides):
    base = {
        "cash": 100000.0,
        "position_contracts": 0,
        "avg_entry_price": 0.0,
        "realized_pnl": 0.0,
        "day_start_equity": 100000.0,
    }
    base.update(overrides)
    return base


def test_compute_kpis_falls_back_to_ledger_cash_with_no_decisions():
    kpis = dd.compute_kpis(_ledger(), [])
    assert kpis["equity"] == 100000.0
    assert kpis["unrealized_pnl"] == 0.0
    assert kpis["today_pnl_pct"] == 0.0
    assert kpis["daily_loss_halt"] == {"halted": False}


def test_compute_kpis_uses_latest_cycle_equity_and_pnl():
    decisions = [
        _cycle("t1", {"equity": 100000.0}),
        _cycle("t2", {
            "equity": 101500.0,
            "unrealized_pnl": 1500.0,
            "daily_loss_halt": {"halted": False},
        }),
    ]
    kpis = dd.compute_kpis(_ledger(position_contracts=2, avg_entry_price=90.0), decisions)
    assert kpis["equity"] == 101500.0
    assert kpis["unrealized_pnl"] == 1500.0
    assert kpis["position_contracts"] == 2
    assert kpis["avg_entry_price"] == 90.0
    assert round(kpis["today_pnl_pct"], 2) == 1.5


def test_compute_kpis_missing_unrealized_pnl_key_treated_as_zero():
    decisions = [_cycle("t1", {"equity": 99000.0})]
    kpis = dd.compute_kpis(_ledger(), decisions)
    assert kpis["unrealized_pnl"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `AttributeError: module 'dashboard_data' has no attribute 'compute_kpis'`

- [ ] **Step 3: Write the minimal implementation**

Append to `dashboard_data.py`:

```python
def compute_kpis(ledger: dict, decisions: list[dict]) -> dict:
    state = latest_portfolio_state(decisions)
    equity = state["equity"] if state else ledger["cash"]
    unrealized_pnl = state.get("unrealized_pnl", 0.0) if state else 0.0
    day_start_equity = ledger.get("day_start_equity") or equity
    today_pnl_pct = ((equity - day_start_equity) / day_start_equity * 100) if day_start_equity else 0.0
    daily_loss_halt = state.get("daily_loss_halt", {"halted": False}) if state else {"halted": False}
    return {
        "equity": equity,
        "position_contracts": ledger["position_contracts"],
        "avg_entry_price": ledger["avg_entry_price"],
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": ledger["realized_pnl"],
        "today_pnl_pct": today_pnl_pct,
        "daily_loss_halt": daily_loss_halt,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add KPI computation for dashboard header row"
```

---

### Task 6: Risk/limits computation

**Files:**
- Modify: `dashboard_data.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `HARD_STOP_LOSS_PCT`, `MAX_DAILY_LOSS_PCT`, `MAX_POSITION_CONTRACTS`, `MARGIN_PER_CONTRACT` from `src/config.py` (values as of this plan: `0.03`, `0.05`, `5`, `6_800.0`), plus `ledger`/`decisions`/`latest_portfolio_state` from earlier tasks.
- Produces: `compute_risk_limits(ledger: dict, decisions: list[dict]) -> dict` with keys `hard_stop_loss_pct`, `unrealized_loss_pct`, `position_contracts`, `max_position_contracts`, `margin_held`, `margin_per_contract`, `max_daily_loss_pct`, `daily_loss_halt`. Percentages are already scaled to human-readable (e.g. `3.0` not `0.03`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_data.py`:

```python
def test_compute_risk_limits_with_no_position():
    risk = dd.compute_risk_limits(_ledger(), [])
    assert risk["hard_stop_loss_pct"] == 3.0
    assert risk["max_daily_loss_pct"] == 5.0
    assert risk["max_position_contracts"] == 5
    assert risk["margin_per_contract"] == 6800.0
    assert risk["unrealized_loss_pct"] == 0.0
    assert risk["daily_loss_halt"] == {"halted": False}


def test_compute_risk_limits_computes_unrealized_loss_pct():
    decisions = [_cycle("t1", {"equity": 98000.0, "unrealized_pnl": -2000.0})]
    risk = dd.compute_risk_limits(_ledger(position_contracts=2, margin_held=13600.0), decisions)
    assert round(risk["unrealized_loss_pct"], 2) == round(2000.0 / 98000.0 * 100, 2)
    assert risk["margin_held"] == 13600.0


def test_compute_risk_limits_positive_unrealized_pnl_is_zero_loss():
    decisions = [_cycle("t1", {"equity": 102000.0, "unrealized_pnl": 2000.0})]
    risk = dd.compute_risk_limits(_ledger(position_contracts=2), decisions)
    assert risk["unrealized_loss_pct"] == 0.0
```

`_ledger` (defined in Task 5) needs `margin_held` in its defaults. Replace
the existing `_ledger` function in `tests/test_dashboard_data.py` with this
version:

```python
def _ledger(**overrides):
    base = {
        "cash": 100000.0,
        "position_contracts": 0,
        "avg_entry_price": 0.0,
        "realized_pnl": 0.0,
        "day_start_equity": 100000.0,
        "margin_held": 0.0,
    }
    base.update(overrides)
    return base
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `AttributeError: module 'dashboard_data' has no attribute 'compute_risk_limits'`

- [ ] **Step 3: Write the minimal implementation**

Add near the top of `dashboard_data.py`, after the existing imports:

```python
import sys

_SRC_DIR = os.path.join(REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from config import (  # noqa: E402
    HARD_STOP_LOSS_PCT,
    MAX_DAILY_LOSS_PCT,
    MAX_POSITION_CONTRACTS,
    MARGIN_PER_CONTRACT,
)
```

Append to `dashboard_data.py`:

```python
def compute_risk_limits(ledger: dict, decisions: list[dict]) -> dict:
    state = latest_portfolio_state(decisions)
    equity = state["equity"] if state else ledger["cash"]
    unrealized_pnl = state.get("unrealized_pnl", 0.0) if state else 0.0
    unrealized_loss_pct = (-unrealized_pnl / equity * 100) if (equity and unrealized_pnl < 0) else 0.0
    daily_loss_halt = state.get("daily_loss_halt", {"halted": False}) if state else {"halted": False}
    return {
        "hard_stop_loss_pct": HARD_STOP_LOSS_PCT * 100,
        "unrealized_loss_pct": unrealized_loss_pct,
        "position_contracts": ledger["position_contracts"],
        "max_position_contracts": MAX_POSITION_CONTRACTS,
        "margin_held": ledger["margin_held"],
        "margin_per_contract": MARGIN_PER_CONTRACT,
        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT * 100,
        "daily_loss_halt": daily_loss_halt,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add risk/limits computation sourced from src/config.py"
```

---

### Task 7: Action distribution over the trade log

**Files:**
- Modify: `dashboard_data.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `ledger["trades"]: list[dict]`, each with an `action: str` key.
- Produces: `action_distribution(ledger: dict) -> dict[str, int]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_data.py`:

```python
def test_action_distribution_counts_by_action():
    ledger = _ledger()
    ledger["trades"] = [
        {"action": "hold"}, {"action": "hold"}, {"action": "open_long"},
    ]
    assert dd.action_distribution(ledger) == {"hold": 2, "open_long": 1}


def test_action_distribution_empty_trades():
    ledger = _ledger()
    ledger["trades"] = []
    assert dd.action_distribution(ledger) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `AttributeError: module 'dashboard_data' has no attribute 'action_distribution'`

- [ ] **Step 3: Write the minimal implementation**

Append to `dashboard_data.py`:

```python
def action_distribution(ledger: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in ledger.get("trades", []):
        action = trade.get("action", "unknown")
        counts[action] = counts.get(action, 0) + 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add trade action distribution helper"
```

---

### Task 8: Calibration bucket stats

**Files:**
- Modify: `dashboard_data.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `records: list[dict]` in the shape `src/calibration.py` reads from `data/calibration_log.jsonl` — each has `avg_confidence: float`, `won: bool`, `realized_pnl: float`.
- Produces: `calibration_stats(records: list[dict]) -> list[dict]`, one dict per bucket (`{"label", "trades", "win_rate", "avg_pnl", "total_pnl"}`), `win_rate`/`avg_pnl`/`total_pnl` are `None` when the bucket has zero trades. Bucket boundaries match `src/calibration.py`'s `BUCKETS` exactly: `0.65-0.75`, `0.75-0.85`, `0.85-1.00`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_data.py`:

```python
def test_calibration_stats_empty_records_all_buckets_empty():
    stats = dd.calibration_stats([])
    assert len(stats) == 3
    assert all(s["trades"] == 0 and s["win_rate"] is None for s in stats)


def test_calibration_stats_buckets_by_confidence():
    records = [
        {"avg_confidence": 0.70, "won": True, "realized_pnl": 500.0},
        {"avg_confidence": 0.72, "won": False, "realized_pnl": -200.0},
        {"avg_confidence": 0.90, "won": True, "realized_pnl": 1000.0},
    ]
    stats = dd.calibration_stats(records)
    low_bucket = next(s for s in stats if s["label"] == "0.65-0.75")
    high_bucket = next(s for s in stats if s["label"] == "0.85-1.00")
    assert low_bucket["trades"] == 2
    assert low_bucket["win_rate"] == 0.5
    assert low_bucket["total_pnl"] == 300.0
    assert high_bucket["trades"] == 1
    assert high_bucket["win_rate"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `AttributeError: module 'dashboard_data' has no attribute 'calibration_stats'`

- [ ] **Step 3: Write the minimal implementation**

Append to `dashboard_data.py`:

```python
CALIBRATION_BUCKETS = [
    (0.65, 0.75, "0.65-0.75"),
    (0.75, 0.85, "0.75-0.85"),
    (0.85, 1.01, "0.85-1.00"),
]


def calibration_stats(records: list[dict]) -> list[dict]:
    stats = []
    for low, high, label in CALIBRATION_BUCKETS:
        bucket = [r for r in records if low <= r["avg_confidence"] < high]
        if not bucket:
            stats.append({
                "label": label, "trades": 0,
                "win_rate": None, "avg_pnl": None, "total_pnl": None,
            })
            continue
        wins = sum(1 for r in bucket if r["won"])
        total_pnl = sum(r["realized_pnl"] for r in bucket)
        stats.append({
            "label": label,
            "trades": len(bucket),
            "win_rate": wins / len(bucket),
            "avg_pnl": total_pnl / len(bucket),
            "total_pnl": total_pnl,
        })
    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 21 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add confidence calibration bucket stats"
```

---

### Task 9: Headline-matching heuristic

**Files:**
- Modify: `dashboard_data.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Consumes: `decisions: list[dict]`. Each cycle's `tool_calls` may include a `get_recent_news` call (`result: {"headlines": [{"title", "summary", "link", "source", "published", ...}, ...]}`, confirmed against `src/tools.py:226`) and/or a `search_news` call (`result: {"results": [{"title", "summary", "link", "source", "date"}, ...]}`, confirmed against `src/tools.py:239` and `src/news.py:search_oil_news`). Each cycle's `final_trade` (when present) is `{"arguments": {"action", "reasoning", ...}, "result": {...}}`.
- Produces: `find_triggering_headline(decisions: list[dict]) -> dict | None`. Returns `None` if there are no decisions at all. Otherwise returns `{"headline": dict | None, "reasoning": str, "action": str, "timestamp": str}` for the most recent cycle whose `final_trade.arguments.action` is `open_long`, `add`, or `close`; returns `None` if every cycle was a `hold` (or had no `final_trade`). `headline` is `None` when that cycle's tool calls returned zero candidate headlines. `headline`, when present, is normalized to `{"title", "summary", "link", "source", "published"}` regardless of which tool it came from.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_data.py`:

```python
def _cycle_with_trade(timestamp, action, reasoning, tool_calls=None):
    cycle = _cycle(timestamp)
    if tool_calls:
        cycle["tool_calls"] = tool_calls
    cycle["final_trade"] = {"arguments": {"action": action, "reasoning": reasoning}, "result": {}}
    return cycle


def test_find_triggering_headline_none_when_all_holds():
    decisions = [_cycle_with_trade("t1", "hold", "nothing new")]
    assert dd.find_triggering_headline(decisions) is None


def test_find_triggering_headline_none_when_no_decisions():
    assert dd.find_triggering_headline([]) is None


def test_find_triggering_headline_picks_best_keyword_match():
    tool_calls = [{
        "tool": "get_recent_news",
        "arguments": {},
        "result": {"headlines": [
            {"title": "OPEC+ announces surprise output cut", "summary": "", "link": "u1", "source": "s1", "published": "p1"},
            {"title": "Local weather forecast for the weekend", "summary": "", "link": "u2", "source": "s2", "published": "p2"},
        ]},
    }]
    decisions = [_cycle_with_trade(
        "t1", "open_long",
        "OPEC+ announced a surprise output cut, tightening supply.",
        tool_calls=tool_calls,
    )]
    result = dd.find_triggering_headline(decisions)
    assert result["action"] == "open_long"
    assert result["headline"]["link"] == "u1"


def test_find_triggering_headline_normalizes_search_news_shape():
    tool_calls = [{
        "tool": "search_news",
        "arguments": {},
        "result": {"results": [
            {"title": "Saudi Aramco confirms disruption", "summary": "supply cut", "link": "u3", "source": "s3", "date": "d3"},
        ]},
    }]
    decisions = [_cycle_with_trade(
        "t1", "close",
        "Saudi Aramco confirmed the disruption is resolved.",
        tool_calls=tool_calls,
    )]
    result = dd.find_triggering_headline(decisions)
    assert result["headline"]["link"] == "u3"
    assert result["headline"]["published"] == "d3"


def test_find_triggering_headline_none_headline_when_cycle_has_no_news_calls():
    decisions = [_cycle_with_trade("t1", "add", "portfolio state check only", tool_calls=[])]
    result = dd.find_triggering_headline(decisions)
    assert result["headline"] is None
    assert result["action"] == "add"


def test_find_triggering_headline_uses_most_recent_non_hold_cycle():
    tool_calls_old = [{"tool": "get_recent_news", "arguments": {}, "result": {"headlines": [
        {"title": "Old catalyst headline", "summary": "", "link": "old", "source": "s", "published": "p"},
    ]}}]
    tool_calls_new = [{"tool": "get_recent_news", "arguments": {}, "result": {"headlines": [
        {"title": "New catalyst headline", "summary": "", "link": "new", "source": "s", "published": "p"},
    ]}}]
    decisions = [
        _cycle_with_trade("t1", "open_long", "Old catalyst headline drove this.", tool_calls=tool_calls_old),
        _cycle_with_trade("t2", "hold", "nothing changed"),
        _cycle_with_trade("t3", "close", "New catalyst headline drove this.", tool_calls=tool_calls_new),
    ]
    result = dd.find_triggering_headline(decisions)
    assert result["headline"]["link"] == "new"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: FAIL with `AttributeError: module 'dashboard_data' has no attribute 'find_triggering_headline'`

- [ ] **Step 3: Write the minimal implementation**

Add `import re` to the top of `dashboard_data.py` alongside the existing imports, then append:

```python
_STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "is", "are",
    "with", "at", "by", "from", "as", "it", "this", "that", "its", "be",
    "has", "have", "will", "was", "were", "not", "no", "new", "after",
    "amid", "over", "into", "than", "but",
}


def _tokenize(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in _STOPWORDS and len(w) > 2
    }


def _cycle_headlines(cycle: dict) -> list[dict]:
    headlines = []
    for call in cycle.get("tool_calls", []):
        tool = call.get("tool")
        result = call.get("result", {})
        if tool == "get_recent_news":
            for h in result.get("headlines", []):
                headlines.append({
                    "title": h.get("title", ""),
                    "summary": h.get("summary", ""),
                    "link": h.get("link", ""),
                    "source": h.get("source", ""),
                    "published": h.get("published", ""),
                })
        elif tool == "search_news":
            for h in result.get("results", []):
                headlines.append({
                    "title": h.get("title", ""),
                    "summary": h.get("summary", ""),
                    "link": h.get("link", ""),
                    "source": h.get("source", ""),
                    "published": h.get("date", ""),
                })
    return headlines


def find_triggering_headline(decisions: list[dict]) -> dict | None:
    for cycle in reversed(decisions):
        trade = cycle.get("final_trade")
        if not trade:
            continue
        action = trade.get("arguments", {}).get("action")
        if action not in ("open_long", "add", "close"):
            continue

        reasoning = trade["arguments"].get("reasoning", "")
        headlines = _cycle_headlines(cycle)
        if not headlines:
            return {
                "headline": None, "reasoning": reasoning,
                "action": action, "timestamp": cycle.get("timestamp"),
            }

        reasoning_tokens = _tokenize(reasoning)
        best = max(
            headlines,
            key=lambda h: len(_tokenize(h["title"] + " " + h["summary"]) & reasoning_tokens),
        )
        return {
            "headline": best, "reasoning": reasoning,
            "action": action, "timestamp": cycle.get("timestamp"),
        }
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: 27 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard_data.py tests/test_dashboard_data.py
git commit -m "Add best-guess headline-to-action matching heuristic"
```

---

### Task 10: Streamlit entrypoint — page skeleton, headline panel, KPI row

**Files:**
- Create: `streamlit_app.py`

**Interfaces:**
- Consumes: every function and constant produced in Tasks 2–9.
- Produces: a running Streamlit page reachable at `http://localhost:8501`.

- [ ] **Step 1: Write the page skeleton and first two sections**

Create `streamlit_app.py`:

```python
import pandas as pd
import streamlit as st

import dashboard_data as dd

st.set_page_config(page_title="Oil News Agent Dashboard", layout="wide")
st.title("Oil News Agent — Mock Fund Dashboard")

ledger = dd.load_ledger()
thesis = dd.load_thesis()
decisions, decisions_skipped = dd.load_jsonl(dd.DECISION_LOG_PATH)
calibration_records, calibration_skipped = dd.load_jsonl(dd.CALIBRATION_LOG_PATH)

if decisions_skipped or calibration_skipped:
    st.caption(
        f"Skipped {decisions_skipped + calibration_skipped} malformed log "
        "line(s) while loading."
    )

if ledger is None:
    st.error("No data/ledger.json found yet — the agent hasn't run.")
    st.stop()

# --- Last headline that triggered action ---
st.subheader("Last headline that triggered action")
trigger = dd.find_triggering_headline(decisions)
if trigger is None:
    st.info("No action taken yet — still flat.")
elif trigger["headline"] is None:
    st.write(f"**{trigger['action']}** — {trigger['reasoning']}")
    st.caption("No headlines were logged for that cycle.")
else:
    h = trigger["headline"]
    st.markdown(f"**[{h['title']}]({h['link']})** — {h['source']} ({h['published']})")
    st.caption("Best-guess match by keyword overlap — not a recorded citation.")
    st.write(f"Action: **{trigger['action']}** — {trigger['reasoning']}")

# --- KPI row ---
kpis = dd.compute_kpis(ledger, decisions)
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Equity", f"${kpis['equity']:,.2f}")
col2.metric("Position", f"{kpis['position_contracts']} @ ${kpis['avg_entry_price']:,.2f}")
col3.metric("Unrealized P&L", f"${kpis['unrealized_pnl']:,.2f}")
col4.metric("Realized P&L", f"${kpis['realized_pnl']:,.2f}")
col5.metric("Today's P&L", f"{kpis['today_pnl_pct']:.2f}%")
col6.metric("Daily Halt", "HALTED" if kpis["daily_loss_halt"].get("halted") else "OK")
```

- [ ] **Step 2: Smoke-test the page starts without crashing**

Run:
```bash
streamlit run streamlit_app.py --server.headless true --server.port 8599 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8599
kill %1
```
Expected: prints `200`.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app.py
git commit -m "Add Streamlit page skeleton with headline panel and KPI row"
```

---

### Task 11: Equity curve, trade log, action distribution

**Files:**
- Modify: `streamlit_app.py`

**Interfaces:**
- Consumes: `dd.get_equity_curve`, `ledger["trades"]`, `dd.action_distribution` from earlier tasks.

- [ ] **Step 1: Append the sections**

Append to `streamlit_app.py`:

```python
# --- Equity curve ---
st.subheader("Equity Curve")
curve = dd.get_equity_curve(decisions)
if curve:
    curve_df = pd.DataFrame(curve).set_index("timestamp")
    st.line_chart(curve_df["equity"])
else:
    st.info("No equity data points logged yet.")

# --- Trade log ---
st.subheader("Trade Log")
trades = ledger.get("trades", [])
if trades:
    st.dataframe(pd.DataFrame(trades), use_container_width=True)
else:
    st.info("No trades logged yet.")

# --- Action distribution ---
st.subheader("Action Distribution")
dist = dd.action_distribution(ledger)
if dist:
    st.bar_chart(pd.Series(dist, name="count"))
else:
    st.info("No trades yet.")
```

- [ ] **Step 2: Smoke-test the page still starts without crashing**

Run:
```bash
streamlit run streamlit_app.py --server.headless true --server.port 8599 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8599
kill %1
```
Expected: prints `200`.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app.py
git commit -m "Add equity curve, trade log, and action distribution sections"
```

---

### Task 12: Active thesis panel, risk/limits panel, calibration section

**Files:**
- Modify: `streamlit_app.py`

**Interfaces:**
- Consumes: `thesis`, `dd.compute_risk_limits`, `dd.calibration_stats` from earlier tasks.

- [ ] **Step 1: Append the sections**

Append to `streamlit_app.py`:

```python
# --- Active thesis ---
st.subheader("Active Thesis")
if thesis is None or not thesis.get("active"):
    st.info("Flat — no active thesis.")
else:
    st.write(f"**Catalyst:** {thesis['catalyst']}")
    st.write(f"**Invalidation criteria:** {thesis['invalidation_criteria']}")
    st.write(f"**Monitoring horizon:** {thesis['monitoring_horizon']}")
    st.write(f"**Entered at:** {thesis['entered_at']} @ ${thesis['price_at_entry']}")
    if thesis.get("notes"):
        st.write("**Notes:**")
        for note in thesis["notes"]:
            st.write(f"- {note}")

# --- Risk & limits ---
st.subheader("Risk & Limits")
risk = dd.compute_risk_limits(ledger, decisions)
st.write(
    f"Hard stop-loss: {risk['hard_stop_loss_pct']:.1f}% "
    f"(current unrealized loss: {risk['unrealized_loss_pct']:.2f}%)"
)
st.write(f"Position: {risk['position_contracts']} / {risk['max_position_contracts']} contracts")
st.write(
    f"Margin held: ${risk['margin_held']:,.2f} "
    f"(${risk['margin_per_contract']:,.2f}/contract)"
)
halt_label = "HALTED" if risk["daily_loss_halt"].get("halted") else "OK"
st.write(f"Daily loss circuit breaker: {risk['max_daily_loss_pct']:.1f}% — {halt_label}")

# --- Confidence calibration ---
st.subheader("Confidence Calibration")
calibration = dd.calibration_stats(calibration_records)
total_closed = sum(s["trades"] for s in calibration)
if total_closed == 0:
    st.info("No closed trades yet — nothing to calibrate against.")
else:
    st.dataframe(pd.DataFrame(calibration), use_container_width=True)
    if total_closed < 20:
        st.caption(
            f"Only {total_closed} closed trade(s) so far — not yet "
            "statistically meaningful."
        )
```

- [ ] **Step 2: Smoke-test the page still starts without crashing**

Run:
```bash
streamlit run streamlit_app.py --server.headless true --server.port 8599 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8599
kill %1
```
Expected: prints `200`.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app.py
git commit -m "Add thesis, risk/limits, and calibration sections"
```

---

### Task 13: End-to-end manual verification against real and fixture data

**Files:**
- None created/modified — this task only verifies Tasks 1–12.

- [ ] **Step 1: Run the full pytest suite one more time**

Run: `pytest tests/test_dashboard_data.py -v`
Expected: all tests pass (27 total from Tasks 2–9).

- [ ] **Step 2: Verify against the repo's real (sparse) data**

Run:
```bash
streamlit run streamlit_app.py --server.headless true --server.port 8599 &
sleep 3
curl -s http://localhost:8599 | grep -c "Oil News Agent" || true
kill %1
```
This repo's current `data/` has ~50+ `hold` cycles, zero closed trades, and no active thesis — confirm by eye (open `http://localhost:8599` in a browser while the server is running, before killing it) that: the headline panel shows "No action taken yet", the equity curve renders a short line instead of erroring, the thesis panel shows "Flat", and the calibration section shows "No closed trades yet".

- [ ] **Step 3: Verify the non-empty-state rendering with throwaway fixture data**

```bash
mkdir -p /tmp/oil_dashboard_fixture/data
python3 - <<'EOF'
import json

ledger = {
    "cash": 95000.0, "position_contracts": 2, "avg_entry_price": 90.0,
    "avg_confidence": 0.8, "margin_held": 13600.0, "realized_pnl": 500.0,
    "trades": [
        {"timestamp": "t1", "action": "open_long", "quantity": 2, "price": 90.0, "confidence": 0.8, "reasoning": "OPEC+ surprise cut"},
        {"timestamp": "t2", "action": "close", "quantity": 2, "price": 92.5, "confidence": 0.8, "reasoning": "Thesis played out"},
    ],
    "last_trade_at": "t2", "day_start_date": "2026-09-27", "day_start_equity": 100000.0,
}
with open("/tmp/oil_dashboard_fixture/data/ledger.json", "w") as f:
    json.dump(ledger, f)

calibration = [{"avg_confidence": 0.8, "won": True, "realized_pnl": 500.0}]
with open("/tmp/oil_dashboard_fixture/data/calibration_log.jsonl", "w") as f:
    f.write(json.dumps(calibration[0]) + "\n")

decisions = [
    {"timestamp": "t1", "tool_calls": [
        {"tool": "get_recent_news", "arguments": {}, "result": {"headlines": [
            {"title": "OPEC+ announces surprise output cut", "summary": "", "link": "u1", "source": "s1", "published": "p1"},
        ]}},
        {"tool": "get_portfolio_state", "arguments": {}, "result": {"equity": 100000.0}},
    ], "final_trade": {"arguments": {"action": "open_long", "reasoning": "OPEC+ surprise cut drove entry"}, "result": {}}},
    {"timestamp": "t2", "tool_calls": [
        {"tool": "get_portfolio_state", "arguments": {}, "result": {"equity": 100500.0, "unrealized_pnl": 500.0}},
    ], "final_trade": {"arguments": {"action": "close", "reasoning": "Thesis played out"}, "result": {}}},
]
with open("/tmp/oil_dashboard_fixture/data/decision_log.jsonl", "w") as f:
    for d in decisions:
        f.write(json.dumps(d) + "\n")

with open("/tmp/oil_dashboard_fixture/data/active_thesis.json", "w") as f:
    json.dump({"active": False}, f)
EOF
```

Temporarily point `dashboard_data.DATA_DIR` at the fixture to verify (do this in a `python3` shell, not by editing the module):

```bash
python3 - <<'EOF'
import dashboard_data as dd
dd.DATA_DIR = "/tmp/oil_dashboard_fixture/data"
dd.LEDGER_PATH = dd.DATA_DIR + "/ledger.json"
dd.THESIS_PATH = dd.DATA_DIR + "/active_thesis.json"
dd.DECISION_LOG_PATH = dd.DATA_DIR + "/decision_log.jsonl"
dd.CALIBRATION_LOG_PATH = dd.DATA_DIR + "/calibration_log.jsonl"

ledger = dd.load_ledger()
decisions, _ = dd.load_jsonl(dd.DECISION_LOG_PATH)
calibration, _ = dd.load_jsonl(dd.CALIBRATION_LOG_PATH)

assert dd.get_equity_curve(decisions) == [
    {"timestamp": "t1", "equity": 100000.0},
    {"timestamp": "t2", "equity": 100500.0},
]
trigger = dd.find_triggering_headline(decisions)
assert trigger["headline"]["link"] == "u1", trigger
stats = dd.calibration_stats(calibration)
assert sum(s["trades"] for s in stats) == 1
print("fixture checks passed")
EOF
```
Expected: prints `fixture checks passed`.

Clean up: `rm -rf /tmp/oil_dashboard_fixture` (throwaway, not committed).

- [ ] **Step 4: Update README with how to run the dashboard**

Add a short section to `README.md` (near the existing tool/architecture docs) explaining `streamlit run streamlit_app.py` for local use, and that it's deployed read-only on Streamlit Community Cloud pointed at this repo. Keep it to 3-5 sentences — match the README's existing terse style.

- [ ] **Step 5: Final commit**

```bash
git add README.md
git commit -m "Document how to run the Streamlit dashboard"
```
