"""
Deterministic risk logic. Nothing in this file is decided by the LLM —
that's the point. The model contributes a *direction* (long/hold/close)
and a *confidence*; everything about *how much* and *when to force an
exit* is computed here from account state and market volatility.

Three responsibilities:
  1. compute_position_size — how many contracts a given confidence level
     and current volatility justify, given a fixed risk budget.
  2. check_hard_stop_loss — should the current open position be force-
     closed right now, regardless of what the model wants to do?
  3. check_daily_loss_limit — has today's loss breached the circuit
     breaker, such that no new trades should be allowed regardless of
     what the model wants?
"""

import math
from datetime import datetime

from config import (
    BASE_RISK_PCT,
    STOP_LOSS_ATR_MULTIPLIER,
    CONTRACT_MULTIPLIER,
    HARD_STOP_LOSS_PCT,
    MAX_DAILY_LOSS_PCT,
    MAX_POSITION_CONTRACTS,
    IST,
)


def compute_position_size(confidence: float, atr: float, equity: float, current_position: int) -> dict:
    """
    Risk-based sizing: risk (confidence x BASE_RISK_PCT) of current
    equity, sized against the stop distance implied by volatility (ATR).

    stop_distance ($ per barrel) = atr x STOP_LOSS_ATR_MULTIPLIER
    risk_per_contract ($)        = stop_distance x CONTRACT_MULTIPLIER
    quantity                     = floor(risk_dollars / risk_per_contract)

    Higher volatility (bigger ATR) -> wider stop -> fewer contracts for
    the same dollar risk. Higher confidence -> more of the risk budget
    used -> more contracts, up to the account's max position cap.
    """
    confidence = max(0.0, min(1.0, confidence))
    risk_dollars = equity * BASE_RISK_PCT * confidence
    stop_distance = atr * STOP_LOSS_ATR_MULTIPLIER
    risk_per_contract = stop_distance * CONTRACT_MULTIPLIER

    if risk_per_contract <= 0:
        return {"quantity": 0, "reason": "Invalid or zero volatility reading — cannot size safely."}

    raw_quantity = math.floor(risk_dollars / risk_per_contract)
    room_left = max(0, MAX_POSITION_CONTRACTS - current_position)
    quantity = min(raw_quantity, room_left)

    return {
        "quantity": quantity,
        "risk_dollars": round(risk_dollars, 2),
        "stop_distance": round(stop_distance, 4),
        "risk_per_contract": round(risk_per_contract, 2),
        "capped_by_max_position": raw_quantity > room_left,
    }


def check_hard_stop_loss(unrealized_pnl: float, equity: float) -> dict:
    """
    Independent of the model: if the open position's unrealized loss
    exceeds HARD_STOP_LOSS_PCT of equity, it must be closed this cycle,
    no matter what the model's reasoning says.
    """
    if equity <= 0:
        return {"triggered": True, "reason": "Equity is zero or negative — force flat immediately."}
    loss_pct = -unrealized_pnl / equity if unrealized_pnl < 0 else 0.0
    if loss_pct >= HARD_STOP_LOSS_PCT:
        return {
            "triggered": True,
            "reason": f"Unrealized loss is {loss_pct:.1%} of equity, breaching the {HARD_STOP_LOSS_PCT:.1%} hard stop.",
        }
    return {"triggered": False}


def _today_str() -> str:
    return datetime.now(IST).date().isoformat()


def get_or_reset_daily_baseline(ledger: dict, current_equity: float) -> float:
    """
    Returns today's starting equity, resetting the baseline if the date
    has rolled over since the last recorded baseline. Mutates ledger
    in place (caller is responsible for saving it).
    """
    today = _today_str()
    if ledger.get("day_start_date") != today:
        ledger["day_start_date"] = today
        ledger["day_start_equity"] = current_equity
    return ledger["day_start_equity"]


def check_daily_loss_limit(ledger: dict, current_equity: float) -> dict:
    """
    Independent of the model: if today's total loss (realized +
    unrealized, relative to the day's starting equity) exceeds
    MAX_DAILY_LOSS_PCT, no new trades (open/add) are allowed for the
    rest of the day. Closing an existing position is still allowed.
    """
    day_start_equity = get_or_reset_daily_baseline(ledger, current_equity)
    if day_start_equity <= 0:
        return {"halted": True, "reason": "Day-start equity is zero or negative."}

    daily_loss_pct = (day_start_equity - current_equity) / day_start_equity
    if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
        return {
            "halted": True,
            "reason": (
                f"Daily loss is {daily_loss_pct:.1%} of the day's starting equity, "
                f"breaching the {MAX_DAILY_LOSS_PCT:.1%} daily circuit breaker. "
                f"No new trades until the next trading day."
            ),
        }
    return {"halted": False}
