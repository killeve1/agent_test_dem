"""
Persistent working memory for the agent: the active investment thesis
behind the currently open position.

Without this the agent has amnesia between cycles — it sees
position_contracts: 1 but not *why* it bought or what would prove it
wrong. The thesis is written when a position is opened (and refined on
add/hold), surfaced at the start of every cycle, and cleared when the
position is closed — including by the hard stop-loss, since clearing
happens inside ledger.execute_mock_trade.

Stored as a JSON file separate from the ledger so it can be read and
edited by hand without touching accounting state.
"""

import json
import os
from datetime import datetime

from config import ACTIVE_THESIS_PATH, IST

MAX_NOTES = 20


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _default_thesis() -> dict:
    return {
        "active": False,
        "catalyst": None,
        "invalidation_criteria": None,
        "monitoring_horizon": None,
        "entered_at": None,
        "price_at_entry": None,
        "last_updated": None,
        "notes": [],
    }


def load_thesis() -> dict:
    if not os.path.exists(ACTIVE_THESIS_PATH):
        return _default_thesis()
    with open(ACTIVE_THESIS_PATH, "r") as f:
        thesis = json.load(f)
    for key, value in _default_thesis().items():
        thesis.setdefault(key, value)
    return thesis


def save_thesis(thesis: dict) -> None:
    os.makedirs(os.path.dirname(ACTIVE_THESIS_PATH), exist_ok=True)
    with open(ACTIVE_THESIS_PATH, "w") as f:
        json.dump(thesis, f, indent=2)


def _append_note(thesis: dict, action: str, price: float, text: str) -> None:
    thesis["notes"].append({"timestamp": _now_iso(), "action": action, "price": price, "note": text})
    thesis["notes"] = thesis["notes"][-MAX_NOTES:]


def open_thesis(price: float, catalyst: str, invalidation_criteria: str,
                monitoring_horizon: str | None = None, note: str | None = None) -> dict:
    """Records a fresh thesis for a newly opened position."""
    now = _now_iso()
    thesis = _default_thesis()
    thesis.update({
        "active": True,
        "catalyst": catalyst,
        "invalidation_criteria": invalidation_criteria,
        "monitoring_horizon": monitoring_horizon,
        "entered_at": now,
        "price_at_entry": price,
        "last_updated": now,
    })
    if note:
        _append_note(thesis, "open_long", price, note)
    save_thesis(thesis)
    return thesis


def update_thesis(action: str, price: float, catalyst: str | None = None,
                  invalidation_criteria: str | None = None, monitoring_horizon: str | None = None,
                  note: str | None = None) -> dict | None:
    """
    Refines the active thesis on add/hold. Only fields that are supplied
    are overwritten. Returns None if there is no active thesis to update.
    """
    thesis = load_thesis()
    if not thesis["active"]:
        return None
    changed = False
    for key, value in (("catalyst", catalyst), ("invalidation_criteria", invalidation_criteria),
                       ("monitoring_horizon", monitoring_horizon)):
        if value:
            thesis[key] = value
            changed = True
    if note:
        _append_note(thesis, action, price, note)
        changed = True
    if changed:
        thesis["last_updated"] = _now_iso()
        save_thesis(thesis)
    return thesis


def clear_thesis() -> dict | None:
    """Resets the thesis on close. Returns the thesis that was active, for the trade record."""
    previous = load_thesis()
    save_thesis(_default_thesis())
    return previous if previous["active"] else None


if __name__ == "__main__":
    print(json.dumps(load_thesis(), indent=2))
