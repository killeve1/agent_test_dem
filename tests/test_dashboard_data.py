import json
import dashboard_data as dd


def test_load_ledger_missing_file_returns_none(tmp_path):
    missing = tmp_path / "no_such_ledger.json"
    assert dd.load_ledger(str(missing)) is None


def test_load_ledger_reads_json(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"cash": 100000.0, "trades": []}))
    result = dd.load_ledger(str(path))
    assert result == {"cash": 100000.0, "trades": []}


def test_load_thesis_missing_file_returns_none(tmp_path):
    missing = tmp_path / "no_such_thesis.json"
    assert dd.load_thesis(str(missing)) is None


def test_load_thesis_reads_json(tmp_path):
    path = tmp_path / "active_thesis.json"
    path.write_text(json.dumps({"active": False}))
    result = dd.load_thesis(str(path))
    assert result == {"active": False}


def test_load_jsonl_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "no_such_log.jsonl"
    records, skipped = dd.load_jsonl(str(missing))
    assert records == []
    assert skipped == 0


def test_load_jsonl_parses_valid_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}\n{"a": 2}\n')
    records, skipped = dd.load_jsonl(str(path))
    assert records == [{"a": 1}, {"a": 2}]
    assert skipped == 0


def test_load_jsonl_skips_malformed_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}\nnot json\n{"a": 2}\n\n')
    records, skipped = dd.load_jsonl(str(path))
    assert records == [{"a": 1}, {"a": 2}]
    assert skipped == 1


def _cycle(timestamp, portfolio_result=None):
    tool_calls = []
    if portfolio_result is not None:
        tool_calls.append({"tool": "get_portfolio_state", "arguments": {}, "result": portfolio_result})
    return {"timestamp": timestamp, "tool_calls": tool_calls}


def test_latest_portfolio_state_returns_none_when_no_cycles_called_it():
    decisions = [_cycle("t1"), _cycle("t2")]
    assert dd.latest_portfolio_state(decisions) is None


def test_latest_portfolio_state_returns_most_recent():
    decisions = [
        _cycle("t1", {"equity": 100000.0}),
        _cycle("t2", {"equity": 100500.0}),
    ]
    assert dd.latest_portfolio_state(decisions) == {"equity": 100500.0}


def test_get_equity_curve_skips_cycles_without_portfolio_state():
    decisions = [
        _cycle("t1", {"equity": 100000.0}),
        _cycle("t2"),
        _cycle("t3", {"equity": 100200.0}),
    ]
    assert dd.get_equity_curve(decisions) == [
        {"timestamp": "t1", "equity": 100000.0},
        {"timestamp": "t3", "equity": 100200.0},
    ]


def test_get_equity_curve_empty_when_no_decisions():
    assert dd.get_equity_curve([]) == []


def _ledger(**overrides):
    base = {
        "cash": 100000.0,
        "position_contracts": 0,
        "avg_entry_price": 0.0,
        "realized_pnl": 0.0,
        "day_start_equity": 100000.0,
        "margin_held": 0.0,
    }
    base.update(overrides)
    return base


def test_compute_kpis_falls_back_to_ledger_cash_with_no_decisions():
    kpis = dd.compute_kpis(_ledger(), [])
    assert kpis["equity"] == 100000.0
    assert kpis["unrealized_pnl"] == 0.0
    assert kpis["today_pnl_pct"] == 0.0
    assert kpis["daily_loss_halt"] == {"halted": False}


def test_compute_kpis_uses_latest_cycle_equity_and_pnl():
    decisions = [
        _cycle("t1", {"equity": 100000.0}),
        _cycle("t2", {
            "equity": 101500.0,
            "unrealized_pnl": 1500.0,
            "daily_loss_halt": {"halted": False},
        }),
    ]
    kpis = dd.compute_kpis(_ledger(position_contracts=2, avg_entry_price=90.0), decisions)
    assert kpis["equity"] == 101500.0
    assert kpis["unrealized_pnl"] == 1500.0
    assert kpis["position_contracts"] == 2
    assert kpis["avg_entry_price"] == 90.0
    assert round(kpis["today_pnl_pct"], 2) == 1.5


def test_compute_kpis_missing_unrealized_pnl_key_treated_as_zero():
    decisions = [_cycle("t1", {"equity": 99000.0})]
    kpis = dd.compute_kpis(_ledger(), decisions)
    assert kpis["unrealized_pnl"] == 0.0


def test_compute_risk_limits_with_no_position():
    risk = dd.compute_risk_limits(_ledger(), [])
    assert risk["hard_stop_loss_pct"] == 3.0
    assert risk["max_daily_loss_pct"] == 5.0
    assert risk["max_position_contracts"] == 5
    assert risk["margin_per_contract"] == 6800.0
    assert risk["unrealized_loss_pct"] == 0.0
    assert risk["daily_loss_halt"] == {"halted": False}


def test_compute_risk_limits_computes_unrealized_loss_pct():
    decisions = [_cycle("t1", {"equity": 98000.0, "unrealized_pnl": -2000.0})]
    risk = dd.compute_risk_limits(_ledger(position_contracts=2, margin_held=13600.0), decisions)
    assert round(risk["unrealized_loss_pct"], 2) == round(2000.0 / 98000.0 * 100, 2)
    assert risk["margin_held"] == 13600.0


def test_compute_risk_limits_positive_unrealized_pnl_is_zero_loss():
    decisions = [_cycle("t1", {"equity": 102000.0, "unrealized_pnl": 2000.0})]
    risk = dd.compute_risk_limits(_ledger(position_contracts=2), decisions)
    assert risk["unrealized_loss_pct"] == 0.0


def test_action_distribution_counts_by_action():
    ledger = _ledger()
    ledger["trades"] = [
        {"action": "hold"}, {"action": "hold"}, {"action": "open_long"},
    ]
    assert dd.action_distribution(ledger) == {"hold": 2, "open_long": 1}


def test_action_distribution_empty_trades():
    ledger = _ledger()
    ledger["trades"] = []
    assert dd.action_distribution(ledger) == {}


def test_calibration_stats_empty_records_all_buckets_empty():
    stats = dd.calibration_stats([])
    assert len(stats) == 3
    assert all(s["trades"] == 0 and s["win_rate"] is None for s in stats)


def test_calibration_stats_buckets_by_confidence():
    records = [
        {"avg_confidence": 0.70, "won": True, "realized_pnl": 500.0},
        {"avg_confidence": 0.72, "won": False, "realized_pnl": -200.0},
        {"avg_confidence": 0.90, "won": True, "realized_pnl": 1000.0},
    ]
    stats = dd.calibration_stats(records)
    low_bucket = next(s for s in stats if s["label"] == "0.65-0.75")
    high_bucket = next(s for s in stats if s["label"] == "0.85-1.00")
    assert low_bucket["trades"] == 2
    assert low_bucket["win_rate"] == 0.5
    assert low_bucket["total_pnl"] == 300.0
    assert high_bucket["trades"] == 1
    assert high_bucket["win_rate"] == 1.0
