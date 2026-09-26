#!/usr/bin/env python3
"""Print a one-shot summary of the mock fund: equity, position, thesis, recent trades.

Reads data/ledger.json, data/active_thesis.json, data/decision_log.jsonl directly —
no API keys or network calls needed. Run from the repo root:

    python .claude/skills/check-oil-status/status.py
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"


def load_json(name):
    path = DATA_DIR / name
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_last_jsonl(name, n=1):
    path = DATA_DIR / name
    if not path.exists():
        return []
    with open(path) as f:
        lines = [line for line in f if line.strip()]
    return [json.loads(line) for line in lines[-n:]]


def main():
    ledger = load_json("ledger.json")
    thesis = load_json("active_thesis.json")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    recent_cycles = load_last_jsonl("decision_log.jsonl", n)

    print("=== Portfolio ===")
    if ledger is None:
        print("No ledger.json found.")
    else:
        print(f"Cash:              ${ledger['cash']:,.2f}")
        print(f"Position:          {ledger['position_contracts']} contracts @ "
              f"${ledger['avg_entry_price']:,.2f}")
        print(f"Margin held:       ${ledger['margin_held']:,.2f}")
        print(f"Realized P&L:      ${ledger['realized_pnl']:,.2f}")
        print(f"Day start equity:  ${ledger['day_start_equity']:,.2f} "
              f"(as of {ledger['day_start_date']})")
        print(f"Last trade at:     {ledger['last_trade_at']}")
        print(f"Total trades logged: {len(ledger['trades'])}")

    print("\n=== Active Thesis ===")
    if thesis is None:
        print("No active_thesis.json found.")
    elif not thesis["active"]:
        print("Flat — no active thesis.")
    else:
        print(f"Catalyst:            {thesis['catalyst']}")
        print(f"Invalidation:        {thesis['invalidation_criteria']}")
        print(f"Monitoring horizon:  {thesis['monitoring_horizon']}")
        print(f"Entered at:          {thesis['entered_at']} @ ${thesis['price_at_entry']}")
        print(f"Last updated:        {thesis['last_updated']}")
        if thesis["notes"]:
            print(f"Latest note:         {thesis['notes'][-1]}")

    print(f"\n=== Last {len(recent_cycles)} decision cycle(s) ===")
    if not recent_cycles:
        print("No decision_log.jsonl found or it's empty.")
    for cycle in recent_cycles:
        ts = cycle.get("timestamp")
        provider = cycle.get("provider", "hard-stop" if cycle.get("forced_by_hard_stop") else "?")
        trade = cycle.get("final_trade")
        if trade:
            args = trade["arguments"]
            print(f"- [{ts}] ({provider}) {args.get('action')} "
                  f"conf={args.get('confidence')} — {args.get('reasoning', '')[:140]}")
        else:
            print(f"- [{ts}] ({provider}) no final trade recorded (partial cycle)")


if __name__ == "__main__":
    main()
