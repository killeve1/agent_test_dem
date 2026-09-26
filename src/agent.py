"""
Entry point for the Oil News Trading Agent. Runs one decision cycle:

  0. BEFORE calling any LLM: check the hard stop-loss. If the open
     position's unrealized loss exceeds 3% of equity, force-close it
     directly against the ledger — the model never gets a vote on risk exits.
  1. Give the model an autonomous, goal-driven mandate.
  2. Multi-provider execution: uses Google Gemini (if configured) with
     automatic fallback to Groq.
  3. Let the model call research tools (news, full article reader, search,
     price, portfolio) autonomously with no rigid sequence.
  4. Conclude with execute_mock_trade and append the audit trail to decision_log.jsonl.

Run this on a schedule (see .github/workflows/run_agent.yml) — each invocation
is one independent decision cycle.
"""

import json
import os
from datetime import datetime

from groq import Groq

from config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
    MAX_AGENT_STEPS,
    DECISION_LOG_PATH,
    MIN_CONFIDENCE_TO_ACT,
    IST,
)
from tools import TOOL_SCHEMAS, dispatch_tool_call
from market import get_current_price
from ledger import get_portfolio_state, execute_mock_trade
from risk import check_hard_stop_loss

SYSTEM_PROMPT = f"""You are an autonomous crude oil portfolio manager managing a \
mock/paper fund. No real money or real exchange is ever involved — every trade \
is a simulation recorded in a transparent ledger.

Portfolio Mandate:
Your primary objective is capital preservation first, and capturing asymmetric upside \
on high-conviction supply/demand disruptions second. You may only hold long positions \
or stay in cash (flat) — shorting is out of scope.

Investigative Autonomy:
- You operate with full discretion over your research process. You are NOT bound to a \
fixed sequence or checklist.
- You have research tools (`get_recent_news`, `read_full_article`, `search_news`), market \
data (`get_current_price`), and portfolio accounting (`get_portfolio_state`).
- Use whatever tools you need based on the situation:
  * If the market is quiet and no major catalysts are present, verify state and hold.
  * If you hold an open position, evaluate its health, price trajectory, and whether your \
thesis remains intact or has been disproven.
  * If a potential catalyst emerges, investigate before taking risk. Never trade on a brief \
headline snippet alone. Use `read_full_article` to examine details and numbers, and \
use `search_news` to check for official statements (Aramco, OPEC, EIA) or resolution status.
- Cash is an active, defensive position. Staying flat is far better than gambling on ambiguous news.

Decision & Risk Rules:
- Conclude every cycle by calling `execute_mock_trade` with your decision: "open_long", \
"add", "close", or "hold", accompanied by concise, evidence-based reasoning.
- To act ("open_long", "add", "close"), your confidence must be at least {MIN_CONFIDENCE_TO_ACT}. \
If your confidence is lower, choose "hold".
- For "open_long" and "add", supply your confidence (0.0 to 1.0). The deterministic risk engine \
computes the position size from your confidence and market volatility (ATR); you do not choose contract counts.
- Two safety controls are enforced in code: a 3% hard stop-loss (force-closed prior to your run if breached), \
and a 5% daily loss circuit breaker. If blocked, accept the limit and hold.
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


def _run_gemini_cycle() -> None:
    """Runs a decision cycle using Google Gemini with automatic tool calling."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    tool_call_log = []
    final_trade_container = {"final_trade": None}

    def get_recent_news(max_results: int = 10) -> dict:
        """Fetch recent oil-market-relevant headlines the agent has not already reacted to."""
        args = {"max_results": max_results}
        res = dispatch_tool_call("get_recent_news", args)
        tool_call_log.append({"tool": "get_recent_news", "arguments": args, "result": res})
        return res

    def read_full_article(url: str) -> dict:
        """Scrape and read the complete text of a news article by URL."""
        args = {"url": url}
        res = dispatch_tool_call("read_full_article", args)
        tool_call_log.append({"tool": "read_full_article", "arguments": args, "result": res})
        return res

    def search_news(query: str, max_results: int = 5) -> dict:
        """Search real-time news and the web for energy market queries, rumors, or confirmations."""
        args = {"query": query, "max_results": max_results}
        res = dispatch_tool_call("search_news", args)
        tool_call_log.append({"tool": "search_news", "arguments": args, "result": res})
        return res

    def get_current_price() -> dict:
        """Get the current live price of the crude oil futures contract."""
        args = {}
        res = dispatch_tool_call("get_current_price", args)
        tool_call_log.append({"tool": "get_current_price", "arguments": args, "result": res})
        return res

    def get_portfolio_state() -> dict:
        """Get current mock fund portfolio: cash, margin, open position, P&L, equity, and halts."""
        args = {}
        res = dispatch_tool_call("get_portfolio_state", args)
        tool_call_log.append({"tool": "get_portfolio_state", "arguments": args, "result": res})
        return res

    def execute_mock_trade(action: str, reasoning: str, confidence: float = 0.0) -> dict:
        """Execute a trade (open_long, add, close, hold) against the mock ledger."""
        args = {"action": action, "reasoning": reasoning, "confidence": confidence}
        res = dispatch_tool_call("execute_mock_trade", args)
        tool_call_log.append({"tool": "execute_mock_trade", "arguments": args, "result": res})
        final_trade_container["final_trade"] = {"arguments": args, "result": res}
        return res

    tools = [
        get_recent_news,
        read_full_article,
        search_news,
        get_current_price,
        get_portfolio_state,
        execute_mock_trade,
    ]

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=tools,
        temperature=0.1,
    )

    client.models.generate_content(
        model=GEMINI_MODEL,
        contents="Assess current oil market news, verify key catalysts, review portfolio state, and conclude with an execute_mock_trade decision.",
        config=config,
    )

    final_trade_result = final_trade_container["final_trade"]

    record = {
        "timestamp": datetime.now(IST).isoformat(),
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "steps_used": len(tool_call_log),
        "tool_calls": tool_call_log,
        "final_trade": final_trade_result,
        "completed": final_trade_result is not None,
    }
    _log_decision(record)

    if final_trade_result is None:
        print("Gemini cycle ended without a final trade decision. Logged partial cycle.")
    else:
        print(f"Gemini cycle complete: {final_trade_result['result']}")


def _run_groq_cycle() -> None:
    """Runs a decision cycle using Groq with OpenAI-compatible tool calling."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set. Export it or set it as a GitHub Actions secret.")

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
            # Nudge model toward finishing with an explicit trade decision
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
        "provider": "groq",
        "model": GROQ_MODEL,
        "steps_used": len(tool_call_log),
        "tool_calls": tool_call_log,
        "final_trade": final_trade_result,
        "completed": final_trade_result is not None,
    }
    _log_decision(record)

    if final_trade_result is None:
        print("Groq cycle ended without a final trade decision (hit step cap). Logged partial cycle.")
    else:
        print(f"Groq cycle complete: {final_trade_result['result']}")


def run_cycle() -> None:
    # 0. Hard stop-loss check happens BEFORE the model is invoked at all.
    forced_record = _check_and_apply_hard_stop()
    if forced_record is not None:
        _log_decision(forced_record)
        return

    provider = LLM_PROVIDER.lower().strip()
    if provider == "gemini":
        if not GEMINI_API_KEY:
            print("Notice: LLM_PROVIDER is 'gemini' but GEMINI_API_KEY is not set. Falling back to Groq.")
            _run_groq_cycle()
        else:
            try:
                print(f"Running agent cycle via Gemini ({GEMINI_MODEL})...")
                _run_gemini_cycle()
            except Exception as e:
                print(f"Gemini execution error: {e}. Falling back to Groq...")
                _run_groq_cycle()
    else:
        print(f"Running agent cycle via Groq ({GROQ_MODEL})...")
        _run_groq_cycle()


if __name__ == "__main__":
    run_cycle()
