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
