#!/usr/bin/env python3
"""
One-time historical correction: replays every recorded decision cycle in
data/decision_log.jsonl against the corrected BASE_RISK_PCT (0.04 -> 0.12,
see src/config.py), using the real ledger.py/thesis.py/risk.py business
logic rather than a reimplementation of it.

Every cycle's recorded LLM decision (action, confidence, reasoning,
catalyst, invalidation_criteria, monitoring_horizon, thesis_note) and its
recorded research tool calls (get_recent_news, search_news,
get_current_price, get_price_history, get_portfolio_state) are replayed
verbatim -- only the deterministic position-sizing math is corrected.
This is a deliberate approximation: it does NOT re-run the LLM, so a
cycle's recorded reasoning may reference a portfolio state (e.g. "we are
flat") that no longer matches the corrected ledger at that point in the
replay. A full LLM re-run was considered and rejected (real API cost,
~100-400+ calls, non-deterministic) in favor of this deterministic,
free, reproducible correction.

Two historical wrinkles this script accounts for:

1. The real clock. ledger._now_iso, thesis._now_iso, and
   risk._today_str all call datetime.now(IST) directly rather than
   accepting a timestamp, so naively replaying would make every
   historical cycle think it's "today" (breaking cooldown and the daily
   loss circuit breaker). These three functions are monkeypatched for
   the duration of each cycle to return that cycle's own historical
   timestamp, so the real business logic runs against the correct
   historical instant instead of wall-clock now().

2. The thesis-requirement gate. ledger.execute_mock_trade's requirement
   that opening a position supply `catalyst` and `invalidation_criteria`
   was added in commit 7a189ae (2026-09-26), AFTER every historical
   open_long attempt in this log (all of which predate 2026-09-26 and
   have catalyst=None, invalidation_criteria=None -- the agent was never
   asked to supply them at the time). Replaying against today's code
   unmodified would reject every attempt with "Opening a position
   requires a thesis" instead of correctly sizing it. Rather than bypass
   the check (which would apply today's sizing fix under yesterday's
   rules, but not today's full rules), this script backfills those two
   fields for any open_long/add cycle that's missing them:
     - catalyst is extracted from that cycle's own recorded reasoning
       text (its first sentence) -- grounded in what the agent actually
       said, not invented.
     - invalidation_criteria is a clearly-labeled placeholder noting it
       was backfilled by this script, since the agent was never asked
       to state one on this historical date. It is NOT presented as
       something the agent said.

Run from the repo root:
    python scripts/replay_sizing_fix.py

Overwrites data/ledger.json, data/active_thesis.json,
data/decision_log.jsonl, and data/calibration_log.jsonl in place. The
original history remains fully recoverable from git history (see the
commit that introduced this script for the exact prior commit SHA).
"""
import json
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
sys.path.insert(0, SRC_DIR)

import config  # noqa: E402
import ledger  # noqa: E402
import risk  # noqa: E402
import thesis  # noqa: E402

INVALIDATION_PLACEHOLDER = (
    "[Backfilled by scripts/replay_sizing_fix.py -- the agent was never asked "
    "for an invalidation criterion on this historical date (the thesis "
    "requirement was added 2026-09-26, after this decision). Re-evaluate "
    "manually.]"
)


def _load_original_cycles() -> list[dict]:
    with open(config.DECISION_LOG_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def _cycle_price(cycle: dict) -> float | None:
    for call in reversed(cycle.get("tool_calls", [])):
        if call.get("tool") == "get_current_price":
            return call["result"]["price"]
    return None


def _cycle_atr(cycle: dict) -> float | None:
    """Recover the ATR reading from the recorded sizing_detail
    (stop_distance = atr * STOP_LOSS_ATR_MULTIPLIER), so re-sizing uses
    the exact same volatility reading the original cycle observed."""
    ft = cycle.get("final_trade")
    if not ft:
        return None
    sizing = ft.get("result", {}).get("sizing_detail")
    if not sizing:
        return None
    return sizing["stop_distance"] / config.STOP_LOSS_ATR_MULTIPLIER


def _backfill_catalyst(reasoning: str) -> str:
    first_sentence = reasoning.split(". ", 1)[0].strip()
    if not first_sentence.endswith("."):
        first_sentence += "."
    return first_sentence[:300]


def _reset_state() -> None:
    for path in (config.LEDGER_PATH, config.ACTIVE_THESIS_PATH, config.CALIBRATION_LOG_PATH):
        if os.path.exists(path):
            os.remove(path)


def main() -> None:
    original_cycles = _load_original_cycles()
    _reset_state()

    corrected_cycles = []
    opens_now_succeed = 0
    hard_stops_triggered = 0

    for cycle in original_cycles:
        ts = cycle["timestamp"]
        cycle_date_str = datetime.fromisoformat(ts).date().isoformat()

        # Patch the three modules' clocks to this cycle's historical instant,
        # so cooldown/daily-reset/thesis-timestamp logic sees the correct
        # historical "now" instead of wall-clock time.
        ledger._now_iso = lambda ts=ts: ts
        thesis._now_iso = lambda ts=ts: ts
        risk._today_str = lambda d=cycle_date_str: d

        price = _cycle_price(cycle)
        new_cycle = dict(cycle)  # keep tool_calls, provider, model, steps_used verbatim
        new_cycle["tool_calls"] = [dict(c) for c in cycle.get("tool_calls", [])]

        if price is None:
            # No price observed this cycle: carry forward as a no-op, same
            # as a cycle that never reached a final decision.
            corrected_cycles.append(new_cycle)
            continue

        # Any get_portfolio_state tool call this cycle read the *old*
        # (stale, uncorrected) ledger at replay time. Replace its recorded
        # result with what the corrected ledger actually looks like right
        # now, so the dashboard's equity curve and KPIs (which read these
        # tool-call results, not ledger.json directly) stay internally
        # consistent with the corrected history instead of showing a flat
        # $100k the whole way through.
        corrected_state = ledger.get_portfolio_state(current_price=price)
        for call in new_cycle["tool_calls"]:
            if call.get("tool") == "get_portfolio_state":
                call["result"] = corrected_state

        # --- Hard stop-loss check, mirroring agent.py's run_cycle() ordering ---
        led = ledger.load_ledger()
        if led["position_contracts"] != 0:
            equity = ledger._current_equity(led, price)
            unrealized = (
                (price - led["avg_entry_price"]) * led["position_contracts"] * config.CONTRACT_MULTIPLIER
            )
            stop_check = risk.check_hard_stop_loss(unrealized_pnl=unrealized, equity=equity)
            if stop_check["triggered"]:
                reasoning = f"AUTOMATIC HARD STOP-LOSS: {stop_check['reason']}"
                result = ledger.execute_mock_trade(action="close", price=price, reasoning=reasoning)
                new_cycle["final_trade"] = {
                    "arguments": {"action": "close", "reasoning": reasoning},
                    "result": result,
                }
                new_cycle["forced_by_hard_stop"] = True
                hard_stops_triggered += 1
                corrected_cycles.append(new_cycle)
                continue

        # --- Replay the recorded decision with corrected sizing ---
        ft = cycle.get("final_trade")
        if not ft:
            corrected_cycles.append(new_cycle)
            continue

        args = dict(ft["arguments"])
        action = args.get("action")
        atr = _cycle_atr(cycle) if action in ("open_long", "add") else None

        if action in ("open_long", "add") and not (args.get("catalyst") and args.get("invalidation_criteria")):
            args["catalyst"] = args.get("catalyst") or _backfill_catalyst(args.get("reasoning", ""))
            args["invalidation_criteria"] = args.get("invalidation_criteria") or INVALIDATION_PLACEHOLDER

        result = ledger.execute_mock_trade(
            action=action,
            price=price,
            reasoning=args.get("reasoning", ""),
            confidence=args.get("confidence"),
            atr=atr,
            catalyst=args.get("catalyst") or None,
            invalidation_criteria=args.get("invalidation_criteria") or None,
            monitoring_horizon=args.get("monitoring_horizon") or None,
            thesis_note=args.get("thesis_note") or None,
        )

        if action in ("open_long", "add") and ft["result"].get("status") != "ok" and result.get("status") == "ok":
            opens_now_succeed += 1

        new_cycle["final_trade"] = {"arguments": args, "result": result}
        corrected_cycles.append(new_cycle)

    with open(config.DECISION_LOG_PATH, "w") as f:
        for c in corrected_cycles:
            f.write(json.dumps(c) + "\n")

    final_ledger = ledger.load_ledger()
    final_thesis = thesis.load_thesis()
    print(f"Replayed {len(original_cycles)} cycles.")
    print(f"Attempts that newly succeeded (were blocked, now filled): {opens_now_succeed}")
    print(f"Hard stop-losses triggered during replay: {hard_stops_triggered}")
    print(
        f"Final position: {final_ledger['position_contracts']} contracts "
        f"@ ${final_ledger['avg_entry_price']:.2f}"
    )
    print(
        f"Final cash: ${final_ledger['cash']:,.2f}  "
        f"realized P&L: ${final_ledger['realized_pnl']:,.2f}"
    )
    print(f"Active thesis: {final_thesis['active']}")


if __name__ == "__main__":
    main()
