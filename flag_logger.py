import json
import os
import threading
from datetime import datetime

FLAG_LOG_FILE = "flags.json"
_lock = threading.Lock()

def log_search_flag(query, results_shown, reason, notes=""):
    """Log when a user flags search results as unhelpful."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "search_flag",
        "query": query,
        "results_shown": results_shown,
        "reason": reason,
        "notes": notes,
    }
    _append(entry)

def log_bill_flag(bill_id, congress, bill_type, reason, notes="", flagged_section="translation"):
    """Log when a user flags a bill translation or timeline as wrong."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "bill_flag",
        "bill_id": bill_id,
        "congress": congress,
        "bill_type": bill_type,
        "reason": reason,
        "notes": notes,
        "flagged_section": flagged_section,
    }
    _append(entry)

def get_flags():
    """Return all flags."""
    try:
        with open(FLAG_LOG_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def _append(entry):
    with _lock:
        log = []
        if os.path.exists(FLAG_LOG_FILE):
            try:
                with open(FLAG_LOG_FILE, "r") as f:
                    log = json.load(f)
            except:
                log = []
        log.append(entry)
        with open(FLAG_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    
    print(f"[FLAG] Logged: {entry['event']} — {entry.get('query') or entry.get('bill_id')}")