"""
Reads data/calibration_log.jsonl (written automatically whenever a
position closes) and reports win rate / average P&L bucketed by the
confidence the model stated when it built that position.

This is the check for whether "confidence" means anything at all. If
0.85-confidence trades don't win noticeably more than 0.65-confidence
ones, the model's self-reported confidence isn't predictive and
shouldn't be trusted as a sizing input without recalibration.

Run directly: python calibration.py
Needs enough CLOSED trades to be meaningful — a handful of data points
will not tell you much; treat early output as illustrative, not conclusive.
"""

import json
import os

from config import CALIBRATION_LOG_PATH

BUCKETS = [
    (0.65, 0.75, "0.65-0.75"),
    (0.75, 0.85, "0.75-0.85"),
    (0.85, 1.01, "0.85-1.00"),
]


def load_records() -> list[dict]:
    if not os.path.exists(CALIBRATION_LOG_PATH):
        return []
    records = []
    with open(CALIBRATION_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def report() -> None:
    records = load_records()
    if not records:
        print("No closed trades logged yet — nothing to calibrate against.")
        return

    print(f"Total closed trades: {len(records)}\n")
    print(f"{'Confidence bucket':<20}{'Trades':<10}{'Win rate':<12}{'Avg P&L':<14}{'Total P&L'}")
    print("-" * 70)

    for low, high, label in BUCKETS:
        bucket = [r for r in records if low <= r["avg_confidence"] < high]
        if not bucket:
            print(f"{label:<20}{'0':<10}{'-':<12}{'-':<14}-")
            continue
        wins = sum(1 for r in bucket if r["won"])
        win_rate = wins / len(bucket)
        total_pnl = sum(r["realized_pnl"] for r in bucket)
        avg_pnl = total_pnl / len(bucket)
        print(f"{label:<20}{len(bucket):<10}{win_rate:<12.1%}${avg_pnl:<13,.2f}${total_pnl:,.2f}")

    overall_wins = sum(1 for r in records if r["won"])
    print("-" * 70)
    print(f"Overall win rate: {overall_wins / len(records):.1%}")
    print(f"Overall total P&L: ${sum(r['realized_pnl'] for r in records):,.2f}")

    if len(records) < 20:
        print(
            "\nNote: fewer than 20 closed trades so far — these numbers are not "
            "yet statistically meaningful. Keep logging before drawing conclusions "
            "about whether confidence predicts outcomes."
        )


if __name__ == "__main__":
    report()
