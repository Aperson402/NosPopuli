import json
import os
import threading
from datetime import datetime

SEARCH_LOG_FILE = "search_log.json"
_lock = threading.Lock()

def log_search(query, query_type, expanded_terms, results_count, result_ids):
    """Log a user search event."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "search",
        "query": query,
        "query_type": query_type,
        "expanded_terms": expanded_terms or [],
        "results_count": results_count,
        "result_ids": result_ids[:5] if result_ids else []
    }
    _append(entry)

def log_bill_opened(bill_id, title, from_query):
    """Log when a user opens a bill detail page."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "bill_opened",
        "bill_id": bill_id,
        "title": title,
        "from_query": from_query
    }
    _append(entry)

def log_member_opened(bioguide_id, name, from_query):
    """Log when a user opens a member profile."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "member_opened",
        "bioguide_id": bioguide_id,
        "name": name,
        "from_query": from_query
    }
    _append(entry)

def get_log():
    """Return full search log."""
    try:
        with open(SEARCH_LOG_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def _append(entry):
    with _lock:
        log = []
        if os.path.exists(SEARCH_LOG_FILE):
            try:
                with open(SEARCH_LOG_FILE, "r") as f:
                    log = json.load(f)
            except:
                log = []
        log.append(entry)
        with open(SEARCH_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)