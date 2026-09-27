"""Read-only data loading and derivation for the Streamlit dashboard.

No `streamlit` import in this module — everything here is plain Python,
testable with pytest, so the dashboard's non-trivial logic (KPI math,
equity-curve extraction, the headline-matching heuristic, calibration
bucketing) has a real test cycle instead of only manual verification.
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO_ROOT, "data")

LEDGER_PATH = os.path.join(DATA_DIR, "ledger.json")
THESIS_PATH = os.path.join(DATA_DIR, "active_thesis.json")
DECISION_LOG_PATH = os.path.join(DATA_DIR, "decision_log.jsonl")
CALIBRATION_LOG_PATH = os.path.join(DATA_DIR, "calibration_log.jsonl")


def load_ledger(path: str = LEDGER_PATH) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_thesis(path: str = THESIS_PATH) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
