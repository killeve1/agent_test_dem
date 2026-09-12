"""
Mock fund ledger. Tracks cash, current position, average entry price,
margin held, running confidence, daily P&L baseline, and full trade
history as a JSON file. This is the agent's only persistent state
between runs.

Accounting model: futures are leveraged — opening a position only ties
up margin per contract, not the full notional value (price x 1,000
barrels). Cash is reduced by margin posted when a position opens, and
increased by margin returned plus/minus realized P&L when it closes.

Position sizing is NOT chosen by the caller directly — for open_long/add,
you supply a confidence score and current ATR, and risk.compute_position_size
determines the actual quantity from the account's risk budget. This is
the deterministic "how much" layer sitting underneath the model's
qualitative "should I" judgment.

The daily loss circuit breaker (risk.check_daily_loss_limit) is enforced
right here, inside execute_mock_trade — not just upstream in the agent
loop — so no caller can trade past it by skipping a check.

No real money or real exchange connection is involved anywhere here.
"""

import json
import os
from datetime import datetime

from config import (
    LEDGER_PATH,
    STARTING_CASH,
    CONTRACT_MULTIPLIER,
    MARGIN_PER_CONTRACT,
    MAX_POSITION_CONTRACTS,
    COOLDOWN_MINUTES,
    CALIBRATION_LOG_PATH,
    IST,
)
from risk import compute_position_size, check_daily_loss_limit, get_or_reset_daily_baseline


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _default_ledger() -> dict:
    return {
        "cash": STARTING_CASH,
        "position_contracts": 0,
        "avg_entry_price": 0.0,
        "avg_confidence": 0.0,
        "margin_held": 0.0,
        "realized_pnl": 0.0,
        "trades": [],
        "last_trade_at": None,
        "day_start_date": None,
        "day_start_equity": STARTING_CASH,
    }


def load_ledger() -> dict:
    if not os.path.exists(LEDGER_PATH):
        return _default_ledger()
    with open(LEDGER_PATH, "r") as f:
        ledger = json.load(f)
    # Backfill fields for ledgers written before they existed
    defaults = _default_ledger()
    for key, value in defaults.items():
        ledger.setdefault(key, value)
    return ledger


def save_ledger(ledger: dict) -> None:
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)


def _current_equity(ledger: dict, current_price: float | None) -> float:
    equity = ledger["cash"] + ledger["margin_held"]
    if current_price is not None and ledger["position_contracts"] != 0:
        equity += (current_price - ledger["avg_entry_price"]) * ledger["position_contracts"] * CONTRACT_MULTIPLIER
    return equity


def get_portfolio_state(current_price: float | None = None) -> dict:
    """
    Tool-facing read of the current mock portfolio.
    "cash_available" is free cash not tied up as margin.
    """
    ledger = load_ledger()
    equity = _current_equity(ledger, current_price)
    state = {
        "cash_available": round(ledger["cash"], 2),
        "margin_held": round(ledger["margin_held"], 2),
        "position_contracts": ledger["position_contracts"],
        "avg_entry_price": round(ledger["avg_entry_price"], 2),
        "avg_confidence_of_position": round(ledger["avg_confidence"], 2),
        "realized_pnl": round(ledger["realized_pnl"], 2),
        "last_trade_at": ledger["last_trade_at"],
        "max_position_contracts": MAX_POSITION_CONTRACTS,
        "margin_per_contract": MARGIN_PER_CONTRACT,
        "cooldown_minutes": COOLDOWN_MINUTES,
        "equity": round(equity, 2),
    }
    if current_price is not None and ledger["position_contracts"] != 0:
        unrealized = (current_price - ledger["avg_entry_price"]) * ledger["position_contracts"] * CONTRACT_MULTIPLIER
        state["unrealized_pnl"] = round(unrealized, 2)

    # Surface the daily circuit-breaker status so the model (and you) can see it
    daily_status = check_daily_loss_limit(ledger, equity)
    save_ledger(ledger)  # persist any baseline reset that check performed
    state["daily_loss_halt"] = daily_status
    return state


def _cooldown_remaining_minutes(ledger: dict) -> float:
    if not ledger["last_trade_at"]:
        return 0.0
    last = datetime.fromisoformat(ledger["last_trade_at"])
    elapsed_min = (datetime.now(IST) - last).total_seconds() / 60.0
    return max(0.0, COOLDOWN_MINUTES - elapsed_min)


def _log_calibration(avg_confidence: float, realized_pnl: float, contracts: int,
                      avg_entry_price: float, close_price: float) -> None:
    os.makedirs(os.path.dirname(CALIBRATION_LOG_PATH), exist_ok=True)
    record = {
        "timestamp": _now_iso(),
        "avg_confidence": round(avg_confidence, 3),
        "realized_pnl": round(realized_pnl, 2),
        "won": realized_pnl > 0,
        "contracts": contracts,
        "avg_entry_price": round(avg_entry_price, 2),
        "close_price": round(close_price, 2),
    }
    with open(CALIBRATION_LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def execute_mock_trade(action: str, price: float, reasoning: str,
                        confidence: float | None = None, atr: float | None = None) -> dict:
    """
    Tool-facing trade execution against the mock ledger only.

    action: "open_long" | "add" | "close" | "hold"

    For "open_long"/"add": confidence (0-1) and atr (current volatility)
    are REQUIRED — quantity is computed by risk.compute_position_size,
    not chosen directly. For "close"/"hold", confidence/atr are ignored.

    Returns a result dict, including whether the trade was accepted or
    blocked (cooldown, position cap, insufficient margin cash, or the
    daily-loss circuit breaker).
    """
    ledger = load_ledger()
    equity_now = _current_equity(ledger, price)

    if action == "hold":
        ledger["trades"].append({
            "timestamp": _now_iso(), "action": "hold", "quantity": 0,
            "price": price, "confidence": confidence, "reasoning": reasoning,
        })
        save_ledger(ledger)
        return {"status": "ok", "action": "hold", "message": "No position change."}

    # Daily circuit breaker — enforced here regardless of caller, for open/add only.
    if action in ("open_long", "add"):
        daily_status = check_daily_loss_limit(ledger, equity_now)
        save_ledger(ledger)  # persist any baseline reset
        if daily_status["halted"]:
            return {"status": "blocked", "reason": daily_status["reason"]}

    cooldown_left = _cooldown_remaining_minutes(ledger)
    if action in ("open_long", "add") and cooldown_left > 0:
        return {
            "status": "blocked",
            "reason": f"Cooldown active — {cooldown_left:.0f} more minutes before another trade is allowed.",
        }

    if action in ("open_long", "add"):
        if confidence is None or atr is None:
            return {"status": "error", "reason": "confidence and atr are required to size an open_long/add trade."}

        sizing = compute_position_size(
            confidence=confidence, atr=atr, equity=equity_now,
            current_position=ledger["position_contracts"],
        )
        quantity = sizing["quantity"]
        if quantity <= 0:
            return {
                "status": "blocked",
                "reason": "Computed position size is 0 contracts (max position reached, or risk budget too small "
                           "for current volatility) — no trade placed.",
                "sizing_detail": sizing,
            }

        required_margin = MARGIN_PER_CONTRACT * quantity
        if required_margin > ledger["cash"]:
            return {
                "status": "blocked",
                "reason": (
                    f"Insufficient cash for margin: need ${required_margin:,.2f} "
                    f"to open {quantity} contract(s), have ${ledger['cash']:,.2f} available."
                ),
                "sizing_detail": sizing,
            }

        new_position = ledger["position_contracts"] + quantity

        # Weighted-average entry price and confidence across the combined position
        total_cost_old = ledger["avg_entry_price"] * ledger["position_contracts"]
        total_cost_new = price * quantity
        ledger["avg_entry_price"] = (total_cost_old + total_cost_new) / new_position

        total_conf_old = ledger["avg_confidence"] * ledger["position_contracts"]
        total_conf_new = confidence * quantity
        ledger["avg_confidence"] = (total_conf_old + total_conf_new) / new_position

        ledger["position_contracts"] = new_position
        ledger["cash"] -= required_margin
        ledger["margin_held"] += required_margin
        ledger["last_trade_at"] = _now_iso()

        entry = {
            "timestamp": _now_iso(), "action": action, "quantity": quantity,
            "price": price, "confidence": confidence, "reasoning": reasoning,
            "sizing_detail": sizing,
        }
        ledger["trades"].append(entry)
        save_ledger(ledger)

        return {
            "status": "ok", "action": action, "quantity_filled": quantity,
            "new_position_contracts": ledger["position_contracts"],
            "avg_entry_price": round(ledger["avg_entry_price"], 2),
            "cash_available": round(ledger["cash"], 2),
            "margin_held": round(ledger["margin_held"], 2),
            "sizing_detail": sizing,
        }

    elif action == "close":
        qty = ledger["position_contracts"]
        if qty == 0:
            return {"status": "blocked", "reason": "No open position to close."}

        realized = (price - ledger["avg_entry_price"]) * qty * CONTRACT_MULTIPLIER
        _log_calibration(ledger["avg_confidence"], realized, qty, ledger["avg_entry_price"], price)

        ledger["realized_pnl"] += realized
        ledger["cash"] += ledger["margin_held"] + realized
        ledger["margin_held"] = 0.0
        ledger["position_contracts"] = 0
        ledger["avg_entry_price"] = 0.0
        ledger["avg_confidence"] = 0.0
        ledger["last_trade_at"] = _now_iso()

        ledger["trades"].append({
            "timestamp": _now_iso(), "action": "close", "quantity": qty,
            "price": price, "confidence": confidence, "reasoning": reasoning,
            "realized_pnl": round(realized, 2),
        })
        save_ledger(ledger)

        return {
            "status": "ok", "action": "close", "contracts_closed": qty,
            "realized_pnl": round(realized, 2),
            "cash_available": round(ledger["cash"], 2),
            "margin_held": round(ledger["margin_held"], 2),
        }

    return {"status": "error", "reason": f"Unknown action '{action}'."}


if __name__ == "__main__":
    print(get_portfolio_state())
