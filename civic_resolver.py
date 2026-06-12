import json
import os
import pgeocode
from documentor_agent import log_action

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "legislators-current.json")

try:
    with open(_DATA_PATH) as f:
        LEGISLATORS = json.load(f)
except FileNotFoundError:
    print(f"[CIVIC] WARNING: legislators file not found at {_DATA_PATH}")
    LEGISLATORS = []

def resolve_zip(zip_code):
    """
    Takes a zip code, returns state and current representatives.
    Uses pgeocode for zip→state, then filters legislators by state.
    """
    
    # Zip to state
    nomi = pgeocode.Nominatim('us')
    result = nomi.query_postal_code(zip_code)
    
    if result is None or str(result.get('state_code', '')) == 'nan':
        print(f"[CIVIC] Could not resolve zip: {zip_code}")
        return None
    
    state = result['state_code']
    
    # Find senators (type=sen, state matches)
    senators = []
    representative = None
    
    for member in LEGISLATORS:
        terms = member.get("terms", [])
        if not terms:
            continue
        
        last_term = terms[-1]
        
        # Must be current (end date 2025 or later or no end date)
        end = last_term.get("end", "")
        if end and end < "2025-01-01":
            continue
        
        member_state = last_term.get("state", "")
        member_type = last_term.get("type", "")
        
        if member_state != state:
            continue
        
        name = f"{member['name']['first']} {member['name']['last']}"
        bioguide = member['id'].get('bioguide', '')
        party = last_term.get("party", "")
        
        person = {
            "name": name,
            "bioguide_id": bioguide,
            "party": party,
            "state": state,
            "chamber": "Senate" if member_type == "sen" else "House",
            "contact_form": last_term.get("contact_form", ""),
            "url": last_term.get("url", ""),
        }
        
        if member_type == "sen":
            senators.append(person)
        elif member_type == "rep":
            # For now take the first rep found
            # House district resolution requires zip→district mapping
            if not representative:
                representative = person
    
    result = {
        "zip_code": zip_code,
        "state": state,
        "senators": senators[:2],
        "representative": representative,
    }
    
    log_action(
        agent_name="civic_resolver",
        action="resolve_zip",
        input_data={"zip_code": zip_code},
        output_data={
            "state": state,
            "senators": [s["name"] for s in senators[:2]],
            "representative": representative["name"] if representative else None
        }
    )
    
    return result

if __name__ == "__main__":
    from documentor_agent import log_action
    
    print("CIVIC RESOLVER TEST")
    print("-" * 40)
    
    for zip_code in ["05401", "10001", "90210"]:
        print(f"Zip: {zip_code}")
        result = resolve_zip(zip_code)
        if result:
            print(f"  State: {result['state']}")
            print(f"  Senators: {[s['name'] for s in result['senators']]}")
            print(f"  Rep: {result['representative']['name'] if result['representative'] else 'None'}")
        print()