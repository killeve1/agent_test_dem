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
