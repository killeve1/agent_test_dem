"""
Entry point. Runs one "cycle" of the agent:

  0. BEFORE calling the model at all: check the hard stop-loss. If the
     open position's unrealized loss has breached the limit, force-close
     it directly against the ledger — the model never gets a vote on
     this. This is a deterministic risk control, not a suggestion.
  1. Give the model a system prompt describing its job and constraints.
  2. Let it call tools (news, price, portfolio, trade) in whatever order
     and however many times it decides it needs, up to a safety cap.
  3. Stop once it calls execute_mock_trade (its decision is final for
     this cycle) or it runs out of steps.
  4. Append a record of the cycle to the decision log.

Run this on a schedule (see .github/workflows/run_agent.yml) — each
invocation is one independent decision cycle, not a long-running process.
"""

import json
import os
from datetime import datetime

from groq import Groq

from config import GROQ_API_KEY, GROQ_MODEL, MAX_AGENT_STEPS, DECISION_LOG_PATH, MIN_CONFIDENCE_TO_ACT, IST
from tools import TOOL_SCHEMAS, dispatch_tool_call
from market import get_current_price
from ledger import get_portfolio_state, execute_mock_trade
from risk import check_hard_stop_loss

SYSTEM_PROMPT = f"""You are a trading agent for a MOCK (paper) fund. No real \
money or real exchange is ever involved — every trade you make is a \
simulation recorded in a ledger.

Your mandate: monitor oil-market news and decide whether to open, add to, \
hold, or close a LONG position in crude oil futures. You may only go long \
or hold/close — shorting is out of scope for this fund.

Process, each cycle:
1. Call get_recent_news to see what's new since your last cycle.
2. If a headline is ambiguous or you need more confirmation, you may call \
get_recent_news again or reason about it — you are not required to act on \
every headline.
3. Call get_portfolio_state to see your current position, cash, equity, and \
whether a cooldown or the daily loss circuit breaker currently blocks new trades.
4. Call get_current_price if you need the live price to reason about entry \
levels.
5. Decide on ONE action for this cycle and call execute_mock_trade exactly \
once with your action and a concise, evidence-based reasoning string. Only \
act (open_long / add / close) if your confidence is at least {MIN_CONFIDENCE_TO_ACT}; \
otherwise call execute_mock_trade with action="hold" so the decision is logged.

IMPORTANT: you do NOT choose a contract quantity. For open_long/add, you \
supply a confidence score (0.0-1.0) and the system computes the actual \
position size from your confidence, current market volatility, and the \
account's risk budget — a higher confidence sizes larger, within limits. \
Focus your reasoning on justifying the confidence level, not on picking a \
trade size.

Two risk controls are enforced automatically, outside your control: a hard \
stop-loss that force-closes the position if it loses too much (checked \
before you're even asked for a decision), and a daily loss circuit breaker \
that blocks new trades for the rest of the day if losses exceed a threshold. \
If a request is blocked by either, accept it and hold rather than trying to \
work around it.

Be skeptical of single ambiguous headlines and of stale news you've already \
reacted to. Prefer clear, high-conviction catalysts (OPEC+ supply decisions, \
major geopolitical supply disruptions, large surprise inventory draws/builds) \
over routine commentary. Always end the cycle by calling execute_mock_trade — \
even 'hold' must be explicit and reasoned.
"""


def _log_decision(record: dict) -> None:
    os.makedirs(os.path.dirname(DECISION_LOG_PATH), exist_ok=True)
    with open(DECISION_LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def _check_and_apply_hard_stop() -> dict | None:
    """
    Runs before the model is even called. If the hard stop-loss is
    breached, force-closes the position directly and returns a record
    of what happened. Returns None if no stop was triggered (or there's
    no open position to check).
    """
    try:
        price_info = get_current_price()
    except Exception as e:
        print(f"Warning: could not fetch price for hard-stop check: {e}")
        return None

    state = get_portfolio_state(current_price=price_info["price"])
    if state["position_contracts"] == 0:
        return None

    unrealized = state.get("unrealized_pnl", 0.0)
    stop_check = check_hard_stop_loss(unrealized_pnl=unrealized, equity=state["equity"])

    if not stop_check["triggered"]:
        return None

    result = execute_mock_trade(
        action="close",
        price=price_info["price"],
        reasoning=f"AUTOMATIC HARD STOP-LOSS: {stop_check['reason']}",
    )
    print(f"Hard stop-loss triggered — position force-closed: {result}")
    return {
        "timestamp": datetime.now(IST).isoformat(),
        "steps_used": 0,
        "tool_calls": [],
        "final_trade": {
            "arguments": {"action": "close", "reasoning": stop_check["reason"]},
            "result": result,
        },
        "completed": True,
        "forced_by_hard_stop": True,
    }


def run_cycle() -> None:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set. Export it or set it as a GitHub Actions secret.")

    # Hard stop-loss check happens BEFORE the model is invoked at all.
    forced_record = _check_and_apply_hard_stop()
    if forced_record is not None:
        _log_decision(forced_record)
        return

    client = Groq(api_key=GROQ_API_KEY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    tool_call_log = []
    final_trade_result = None

    for step in range(MAX_AGENT_STEPS):
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            # Model responded with plain text instead of a tool call —
            # nudge it back toward finishing with an explicit trade decision.
            messages.append({
                "role": "user",
                "content": "Please conclude this cycle by calling execute_mock_trade.",
            })
            continue

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}

            result = dispatch_tool_call(name, arguments)
            tool_call_log.append({"tool": name, "arguments": arguments, "result": result})

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })

            if name == "execute_mock_trade":
                final_trade_result = {"arguments": arguments, "result": result}

        if final_trade_result is not None:
            break

    record = {
        "timestamp": datetime.now(IST).isoformat(),
        "steps_used": len(tool_call_log),
        "tool_calls": tool_call_log,
        "final_trade": final_trade_result,
        "completed": final_trade_result is not None,
    }
    _log_decision(record)

    if final_trade_result is None:
        print("Cycle ended without a final trade decision (hit step cap). Logged partial cycle.")
    else:
        print(f"Cycle complete: {final_trade_result['result']}")


if __name__ == "__main__":
    run_cycle()
