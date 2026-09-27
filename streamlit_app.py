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

# --- Equity curve ---
st.subheader("Equity Curve")
curve = dd.get_equity_curve(decisions)
if curve:
    curve_df = pd.DataFrame(curve).set_index("timestamp")
    st.line_chart(curve_df["equity"])
else:
    st.info("No equity data points logged yet.")

# --- Trade log ---
st.subheader("Trade Log")
trades = ledger.get("trades", [])
if trades:
    st.dataframe(pd.DataFrame(trades), use_container_width=True)
else:
    st.info("No trades logged yet.")

# --- Action distribution ---
st.subheader("Action Distribution")
dist = dd.action_distribution(ledger)
if dist:
    st.bar_chart(pd.Series(dist, name="count"))
else:
    st.info("No trades yet.")

# --- Active thesis ---
st.subheader("Active Thesis")
if thesis is None or not thesis.get("active"):
    st.info("Flat — no active thesis.")
else:
    st.write(f"**Catalyst:** {thesis['catalyst']}")
    st.write(f"**Invalidation criteria:** {thesis['invalidation_criteria']}")
    st.write(f"**Monitoring horizon:** {thesis['monitoring_horizon']}")
    st.write(f"**Entered at:** {thesis['entered_at']} @ ${thesis['price_at_entry']}")
    if thesis.get("notes"):
        st.write("**Notes:**")
        for note in thesis["notes"]:
            st.write(f"- {note}")

# --- Risk & limits ---
st.subheader("Risk & Limits")
risk = dd.compute_risk_limits(ledger, decisions)
st.write(
    f"Hard stop-loss: {risk['hard_stop_loss_pct']:.1f}% "
    f"(current unrealized loss: {risk['unrealized_loss_pct']:.2f}%)"
)
st.write(f"Position: {risk['position_contracts']} / {risk['max_position_contracts']} contracts")
st.write(
    f"Margin held: ${risk['margin_held']:,.2f} "
    f"(${risk['margin_per_contract']:,.2f}/contract)"
)
halt_label = "HALTED" if risk["daily_loss_halt"].get("halted") else "OK"
st.write(f"Daily loss circuit breaker: {risk['max_daily_loss_pct']:.1f}% — {halt_label}")

# --- Confidence calibration ---
st.subheader("Confidence Calibration")
calibration = dd.calibration_stats(calibration_records)
total_closed = sum(s["trades"] for s in calibration)
if total_closed == 0:
    st.info("No closed trades yet — nothing to calibrate against.")
else:
    st.dataframe(pd.DataFrame(calibration), use_container_width=True)
    if total_closed < 20:
        st.caption(
            f"Only {total_closed} closed trade(s) so far — not yet "
            "statistically meaningful."
        )
