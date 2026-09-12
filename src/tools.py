"""
Defines the tools available to the agent (Groq/OpenAI-compatible function
schemas) and dispatches tool calls to the real Python implementations.

This is the layer that turns the LLM from a "classifier" into an agent:
it decides which of these to call, in what order, and how many times,
based on what it's trying to figure out.

Note on execute_mock_trade: the model supplies a confidence score, not a
contract quantity. Actual position size is computed deterministically
(risk.compute_position_size, via ledger.execute_mock_trade) from that
confidence, current volatility (ATR), and account equity — see risk.py.
"""

import json

from news import fetch_headlines
from market import get_current_price, get_volatility
from ledger import get_portfolio_state, execute_mock_trade
from config import FUTURES_SYMBOL

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_recent_news",
            "description": (
                "Fetch recent oil-market-relevant headlines the agent has not "
                "already reacted to. Use this first, and again if you need more "
                "context (e.g. a headline is ambiguous or contradicts recent news)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of headlines to return.",
                        "default": 10,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_price",
            "description": f"Get the current price of the {FUTURES_SYMBOL} futures contract.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_state",
            "description": (
                "Get the current mock portfolio: cash, margin held, open position "
                "size, average entry price/confidence, realized/unrealized P&L, "
                "equity, whether a cooldown is active, and whether the daily loss "
                "circuit breaker has halted new trades."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_mock_trade",
            "description": (
                "Execute a trade against the MOCK fund only — no real money or "
                "real exchange is involved. Use 'hold' when you decide not to "
                "act, so the decision (and reasoning) is still logged. For "
                "'open_long'/'add', you do NOT choose the contract quantity — "
                "you provide a confidence score and the system computes the "
                "appropriately sized position from your confidence, current "
                "market volatility, and account risk limits. If the daily loss "
                "circuit breaker is active or a cooldown is in effect, open/add "
                "will be blocked regardless of confidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open_long", "add", "close", "hold"],
                        "description": (
                            "open_long: start a new long position. add: increase an "
                            "existing long. close: exit the full position. hold: take no action."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": (
                            "Required for 'open_long'/'add'. Your confidence (0.0-1.0) that "
                            "this is a good trade right now. Drives position size directly — "
                            "higher confidence sizes larger, within risk limits. Ignored for "
                            "'close'/'hold'."
                        ),
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Concise justification for this decision, citing the specific news/price evidence.",
                    },
                },
                "required": ["action", "reasoning"],
            },
        },
    },
]


def dispatch_tool_call(name: str, arguments: dict) -> dict:
    """
    Executes the requested tool and returns a JSON-serializable result.
    The agent loop is responsible for feeding this back to the model.
    """
    if name == "get_recent_news":
        max_results = arguments.get("max_results", 10)
        return {"headlines": fetch_headlines(max_results=max_results)}

    if name == "get_current_price":
        return get_current_price()

    if name == "get_portfolio_state":
        # Include current price context so P&L is meaningful
        try:
            price_info = get_current_price()
            return get_portfolio_state(current_price=price_info["price"])
        except Exception:
            return get_portfolio_state()

    if name == "execute_mock_trade":
        price_info = get_current_price()
        action = arguments["action"]

        atr = None
        if action in ("open_long", "add"):
            try:
                atr = get_volatility()["atr"]
            except Exception as e:
                return {"status": "error", "reason": f"Could not compute volatility for sizing: {e}"}

        return execute_mock_trade(
            action=action,
            price=price_info["price"],
            reasoning=arguments.get("reasoning", ""),
            confidence=arguments.get("confidence"),
            atr=atr,
        )

    return {"error": f"Unknown tool '{name}'"}
