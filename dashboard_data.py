"""Read-only data loading and derivation for the Streamlit dashboard.

No `streamlit` import in this module — everything here is plain Python,
testable with pytest, so the dashboard's non-trivial logic (KPI math,
equity-curve extraction, the headline-matching heuristic, calibration
bucketing) has a real test cycle instead of only manual verification.
"""
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

_SRC_DIR = os.path.join(REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from config import (  # noqa: E402
    HARD_STOP_LOSS_PCT,
    MAX_DAILY_LOSS_PCT,
    MAX_POSITION_CONTRACTS,
    MARGIN_PER_CONTRACT,
)
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


def action_distribution(ledger: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in ledger.get("trades", []):
        action = trade.get("action", "unknown")
        counts[action] = counts.get(action, 0) + 1
    return counts


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
