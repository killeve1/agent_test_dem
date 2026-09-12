"""
Central configuration for the oil-news trading agent.
Tweak these values to change what the agent watches and how it behaves.
"""

import os

# --- Timezone for all recorded timestamps ---
from datetime import timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# --- LLM (Groq) ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile was decommissioned by Groq on 08/16/2026
MAX_AGENT_STEPS = 6  # safety cap on tool-call loop iterations per run

# --- Market data ---
FUTURES_SYMBOL = "CL=F"  # WTI Crude front-month via Yahoo Finance (yfinance)
                          # Use "BZ=F" for Brent instead

# --- News sources (RSS feeds, no API key needed) ---
RSS_FEEDS = [
    "https://oilprice.com/rss/main",
    "https://www.eia.gov/rss/todayinenergy.xml",
    "https://www.investing.com/rss/news_301.rss",  # commodities news
]

# Keywords used to filter headlines down to oil-relevant ones
OIL_KEYWORDS = [
    "opec", "opec+", "wti", "brent", "crude", "oil price", "oil output",
    "oil production", "barrel", "strait of hormuz", "saudi", "iran",
    "inventories", "eia report", "petroleum", "rig count",
]

# --- Mock fund parameters ---
CONTRACT_MULTIPLIER = 1000  # 1 WTI futures contract = 1,000 barrels (for mock P&L math)
# Real futures only require posting MARGIN, not the full notional value of the
# contract — this is what makes them leveraged. CME's WTI (CL) initial margin
# has recently run around $6,500-$7,000/contract but moves with volatility;
# check https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude-oil.margins.html
# and update this if you want the mock fund to track it more precisely.
MARGIN_PER_CONTRACT = 6_800.0
STARTING_CASH = 100_000.0
MAX_POSITION_CONTRACTS = 5      # hard cap on how large the long can get
MIN_CONFIDENCE_TO_ACT = 0.65    # agent must be at least this confident to trade
COOLDOWN_MINUTES = 60           # minimum gap between trades

# --- Position sizing (risk-based, not a flat contract count) ---
# Quantity is computed, not chosen by the model: the model supplies a
# confidence score (0-1); the size is then risk_dollars / (stop-distance in $).
# NOTE on scale: one full-size WTI contract represents 1,000 barrels
# (~$100k of notional exposure at $100/barrel), so a $100k mock account
# risking a conservative 1-2% per trade will often size to 0 contracts
# under normal volatility — that's a real mismatch between account size
# and instrument size, not a bug in the formula. 4% keeps sizing usable
# at this account size under typical volatility while still correctly
# sizing down to 0 in a volatility spike (the risk model refusing to
# take a full contract's worth of risk is intentional, not an error).
# If you want finer-grained sizing, switch FUTURES_SYMBOL to CME's Micro
# WTI (100 barrels/contract) and set CONTRACT_MULTIPLIER = 100 instead.
BASE_RISK_PCT = 0.04           # fraction of current equity risked on a full-confidence (1.0) trade
ATR_LOOKBACK_DAYS = 14        # lookback window for Average True Range (volatility proxy)
STOP_LOSS_ATR_MULTIPLIER = 1.5  # stop distance = ATR x this multiplier

# --- Risk controls enforced in code, not by the model ---
HARD_STOP_LOSS_PCT = 0.03     # force-close the position if unrealized loss exceeds this % of equity
MAX_DAILY_LOSS_PCT = 0.05     # halt all new trades for the day if daily loss exceeds this % of equity

# --- File paths (relative to repo root, so GitHub Actions can commit them back) ---
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
LEDGER_PATH = os.path.join(DATA_DIR, "ledger.json")
SEEN_NEWS_PATH = os.path.join(DATA_DIR, "seen_headlines.json")
DECISION_LOG_PATH = os.path.join(DATA_DIR, "decision_log.jsonl")
CALIBRATION_LOG_PATH = os.path.join(DATA_DIR, "calibration_log.jsonl")
