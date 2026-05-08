import json
import os
from datetime import datetime

LOG_FILE = "agent_log.json"

def log_action(agent_name, action, input_data, output_data):
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "agent": agent_name,
        "action": action,
        "input": input_data,
        "output": output_data
    }
    
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            log = json.load(f)
    else:
        log = []
    
    log.append(entry)
    
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)
    
    print(f"[DOCUMENTOR] Logged: {agent_name} → {action}")