"""
Entry point for the Oil News Trading Agent. Runs one decision cycle:

  0. BEFORE calling any LLM: check the hard stop-loss. If the open
     position's unrealized loss exceeds 3% of equity, force-close it
     directly against the ledger — the model never gets a vote on risk exits.
  1. Give the model an autonomous, goal-driven mandate.
  2. Multi-provider execution: uses Google Gemini (if configured) with
     automatic fallback to Groq.
  3. Let the model call research tools (news, full article reader, search,
     price, price history, portfolio) autonomously with no rigid sequence.
     If a position is open, its stored thesis (thesis.py) is put in front
     of the model first so it re-validates rather than starting from scratch.
  4. Conclude with execute_mock_trade and append the audit trail to decision_log.jsonl.

Run this on a schedule (see .github/workflows/run_agent.yml) — each invocation
is one independent decision cycle.
"""

import json
import os
from datetime import datetime

from groq import Groq, BadRequestError

from config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
    MAX_AGENT_STEPS,
    GROQ_MAX_COMPLETION_TOKENS,
    GROQ_CONTEXT_BUDGET_CHARS,
    DECISION_LOG_PATH,
    MIN_CONFIDENCE_TO_ACT,
    IST,
)
from tools import TOOL_SCHEMAS, dispatch_tool_call
from market import get_current_price
from ledger import get_portfolio_state, execute_mock_trade
from risk import check_hard_stop_loss
from thesis import load_thesis

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
data (`get_current_price`, `get_price_history`), and portfolio accounting (`get_portfolio_state`).
- Use whatever tools you need based on the situation:
  * If the market is quiet and no major catalysts are present, verify state and hold.
  * If you hold an open position, your FIRST task is to re-validate your stored thesis: \
check whether any invalidation criterion has been met and what happened with the events \
on your monitoring horizon. If the thesis is disproven, close. Record your verdict in `thesis_note`.
  * Before entering, use `get_price_history` to check whether the move has already been \
priced in (you'd be buying the top of a spike) or is just beginning.
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
- When opening a position from flat, you must record a thesis: `catalyst` (the specific disruption), \
`invalidation_criteria` (the concrete event or price action that proves you wrong), and \
`monitoring_horizon` (the upcoming events you are waiting on). This is your memory for future cycles.
- Two safety controls are enforced in code: a 3% hard stop-loss (force-closed prior to your run if breached), \
and a 5% daily loss circuit breaker. If blocked, accept the limit and hold.
"""


def _build_cycle_briefing() -> str:
    """The opening user message for a cycle — carries the active thesis across runs."""
    thesis = load_thesis()
    if not thesis["active"]:
        return (
            "You are currently flat (no active thesis). Assess current oil market news, verify key "
            "catalysts, check price history for context, review portfolio state, and conclude with "
            "an execute_mock_trade decision."
        )
    return (
        "You hold an open position. This is the active thesis you recorded in earlier cycles:\n"
        f"{json.dumps(thesis, indent=2)}\n\n"
        "First, determine whether this thesis is still intact, strengthened, or disproven: check "
        "the invalidation criteria against the latest news and price action, and check the status "
        "of the events on your monitoring horizon. Then decide (hold / add / close) and conclude "
        "with execute_mock_trade, putting your thesis verdict in thesis_note."
    )


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

    # Retry transient overload (503) / rate-limit (429) errors before falling back to Groq
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=4, initial_delay=5.0, http_status_codes=[429, 500, 503]),
        ),
    )
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

    def get_price_history(period: str = "1d", interval: str = "15m") -> dict:
        """Get recent OHLCV candles, period high/low and % change for crude futures.
        period: one of 1d, 5d, 1mo, 3mo. interval: one of 5m, 15m, 30m, 1h, 1d."""
        args = {"period": period, "interval": interval}
        res = dispatch_tool_call("get_price_history", args)
        tool_call_log.append({"tool": "get_price_history", "arguments": args, "result": res})
        return res

    def get_portfolio_state() -> dict:
        """Get current mock fund portfolio: cash, margin, open position, P&L, equity, halts, and active thesis."""
        args = {}
        res = dispatch_tool_call("get_portfolio_state", args)
        tool_call_log.append({"tool": "get_portfolio_state", "arguments": args, "result": res})
        return res

    def execute_mock_trade(action: str, reasoning: str, confidence: float = 0.0,
                           catalyst: str = "", invalidation_criteria: str = "",
                           monitoring_horizon: str = "", thesis_note: str = "") -> dict:
        """Execute a trade (open_long, add, close, hold) against the mock ledger.
        open_long from flat requires catalyst and invalidation_criteria (plus ideally
        monitoring_horizon). thesis_note records your per-cycle verdict on the thesis."""
        args = {
            "action": action, "reasoning": reasoning, "confidence": confidence,
            "catalyst": catalyst, "invalidation_criteria": invalidation_criteria,
            "monitoring_horizon": monitoring_horizon, "thesis_note": thesis_note,
        }
        res = dispatch_tool_call("execute_mock_trade", args)
        tool_call_log.append({"tool": "execute_mock_trade", "arguments": args, "result": res})
        final_trade_container["final_trade"] = {"arguments": args, "result": res}
        return res

    tools = [
        get_recent_news,
        read_full_article,
        search_news,
        get_current_price,
        get_price_history,
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
        contents=_build_cycle_briefing(),
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


def _compact_messages(messages: list[dict]) -> None:
    """
    Keeps the Groq conversation under GROQ_CONTEXT_BUDGET_CHARS by truncating the
    oldest tool results first. The system prompt, briefing, and assistant turns
    are kept intact so the model still knows what it already looked at.
    """
    def total() -> int:
        return sum(len(json.dumps(m)) for m in messages)

    for m in messages:
        if total() <= GROQ_CONTEXT_BUDGET_CHARS:
            return
        if m.get("role") == "tool" and len(m["content"]) > 300:
            m["content"] = m["content"][:300] + "... [truncated to save context; re-call the tool if needed]"


def _run_groq_cycle() -> None:
    """Runs a decision cycle using Groq with OpenAI-compatible tool calling."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set. Export it or set it as a GitHub Actions secret.")

    # Extra retries so 429 per-minute token limits wait out (SDK honours retry-after)
    client = Groq(api_key=GROQ_API_KEY, max_retries=6)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_cycle_briefing()},
    ]

    tool_call_log = []
    final_trade_result = None

    for step in range(MAX_AGENT_STEPS):
        _compact_messages(messages)
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_completion_tokens=GROQ_MAX_COMPLETION_TOKENS,
            )
        except BadRequestError as e:
            # Groq validates tool-call arguments server-side and rejects the whole
            # request on a malformed call — feed the error back and let the model retry.
            if "tool_use_failed" not in str(e):
                raise
            messages.append({
                "role": "user",
                "content": f"Your last tool call was rejected: {e.message}. Fix the arguments and try again.",
            })
            continue
        msg = response.choices[0].message
        # Drop the model's reasoning text — it isn't needed later and would be resent every step
        messages.append(msg.model_dump(exclude_none=True, exclude={"reasoning"}))

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
