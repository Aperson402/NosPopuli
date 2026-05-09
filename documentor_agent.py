import json
import os
from datetime import datetime
import threading

LOG_FILE = "agent_log.json"
_lock = threading.Lock()  # Only one thread can write at a time

def log_action(agent_name, action, input_data, output_data):
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "action": action,
        "input": input_data,
        "output": output_data
    }
    
    with _lock:  # All other agents wait here until lock is released
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                log = json.load(f)
        else:
            log = []
        
        log.append(entry)
        
        with open(LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    
    print(f"[DOCUMENTOR] Logged: {agent_name} → {action}")