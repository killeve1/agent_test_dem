import pandas as pd
import streamlit as st

import dashboard_data as dd

st.set_page_config(page_title="Oil News Agent Dashboard", layout="wide")
st.title("Oil News Agent — Mock Fund Dashboard")

ledger = dd.load_ledger()
thesis = dd.load_thesis()
decisions, decisions_skipped = dd.load_jsonl(dd.DECISION_LOG_PATH)
calibration_records, calibration_skipped = dd.load_jsonl(dd.CALIBRATION_LOG_PATH)

if decisions_skipped or calibration_skipped:
    st.caption(
        f"Skipped {decisions_skipped + calibration_skipped} malformed log "
        "line(s) while loading."
    )

if ledger is None:
    st.error("No data/ledger.json found yet — the agent hasn't run.")
    st.stop()

# --- Last headline that triggered action ---
st.subheader("Last headline that triggered action")
trigger = dd.find_triggering_headline(decisions)
if trigger is None:
    st.info("No action taken yet — still flat.")
elif trigger["headline"] is None:
    st.write(f"**{trigger['action']}** — {trigger['reasoning']}")
    st.caption("No headlines were logged for that cycle.")
else:
    h = trigger["headline"]
    st.markdown(f"**[{h['title']}]({h['link']})** — {h['source']} ({h['published']})")
    st.caption("Best-guess match by keyword overlap — not a recorded citation.")
    st.write(f"Action: **{trigger['action']}** — {trigger['reasoning']}")

# --- KPI row ---
kpis = dd.compute_kpis(ledger, decisions)
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Equity", f"${kpis['equity']:,.2f}")
col2.metric("Position", f"{kpis['position_contracts']} @ ${kpis['avg_entry_price']:,.2f}")
col3.metric("Unrealized P&L", f"${kpis['unrealized_pnl']:,.2f}")
col4.metric("Realized P&L", f"${kpis['realized_pnl']:,.2f}")
col5.metric("Today's P&L", f"{kpis['today_pnl_pct']:.2f}%")
col6.metric("Daily Halt", "HALTED" if kpis["daily_loss_halt"].get("halted") else "OK")
