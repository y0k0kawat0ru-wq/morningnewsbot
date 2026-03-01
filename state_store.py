from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).resolve().parent / "state.json"
DEFAULT_STATE = {
    "last_keys": [],
    "last_summary_hash": "",
    "last_run_jst": "",
}


def load_state() -> dict[str, Any]:
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return DEFAULT_STATE.copy()
        return {
            "last_keys": list(data.get("last_keys", [])),
            "last_summary_hash": str(data.get("last_summary_hash", "")),
            "last_run_jst": str(data.get("last_run_jst", "")),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return DEFAULT_STATE.copy()


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_FILE.with_suffix(".json.tmp")
    payload = {
        "last_keys": list(state.get("last_keys", [])),
        "last_summary_hash": str(state.get("last_summary_hash", "")),
        "last_run_jst": str(state.get("last_run_jst", "")),
    }
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, STATE_FILE)
