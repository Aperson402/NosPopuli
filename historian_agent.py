import requests
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")

def fetch_bill_actions(congress_number, bill_type, bill_number):
    """Gets the full action history of a bill - every step it took through Congress"""
    
    url = f"https://api.congress.gov/v3/bill/{congress_number}/{bill_type}/{bill_number}/actions"
    
    params = {
        "api_key": CONGRESS_API_KEY,
        "format": "json",
        "limit": 20
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        actions = data["actions"]
        
        log_action(
            agent_name="historian",
            action="fetch_bill_actions",
            input_data={"congress": congress_number, "type": bill_type, "number": bill_number},
            output_data={"action_count": len(actions)}
        )
        
        return actions
    else:
        print(f"Error: {response.status_code}")
        return None

def fetch_related_bills(congress_number, bill_type, bill_number):
    """Finds bills related to this one"""
    
    url = f"https://api.congress.gov/v3/bill/{congress_number}/{bill_type}/{bill_number}/relatedbills"
    
    params = {
        "api_key": CONGRESS_API_KEY,
        "format": "json",
        "limit": 5
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        related = data.get("relatedBills", [])
        
        log_action(
            agent_name="historian",
            action="fetch_related_bills",
            input_data={"congress": congress_number, "type": bill_type, "number": bill_number},
            output_data={"related_count": len(related)}
        )
        
        return related
    else:
        print(f"Error: {response.status_code}")
        return None

def summarize_history(actions, client):
    """Uses AI to turn the raw action list into a readable timeline"""
    
    if not actions:
        return "No action history available."
    
    action_text = "\n".join([
        f"{a['actionDate']}: {a['text']}"
        for a in actions
    ])
    
    prompt = f"""
    You are a legislative historian.
    Your only job is to explain how a bill moved through Congress
    in plain chronological language an ordinary person can follow.
    Be concise. Use plain English. No jargon.
    
    Raw action history:
    {action_text}
    
    Write a short readable timeline of how this bill became law.
    """
    
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    summary = message.content[0].text
    
    log_action(
        agent_name="historian",
        action="summarize_history",
        input_data={"action_count": len(actions)},
        output_data={"preview": summary[:100]}
    )
    
    return summary

if __name__ == "__main__":
    import anthropic
    
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    print("HISTORIAN AGENT")
    print("-" * 40)
    
    actions = fetch_bill_actions(111, "hr", 3590)
    related = fetch_related_bills(111, "hr", 3590)
    
    print(f"Found {len(actions)} actions in history")
    print(f"Found {len(related)} related bills")
    print()
    print("TIMELINE:")
    print("-" * 40)
    timeline = summarize_history(actions, client)
    print(timeline)
    
    if related:
        print()
        print("RELATED BILLS:")
        print("-" * 40)
        for bill in related[:3]:
            print(f"- {bill.get('title', 'No title')} ({bill.get('relationshipDetails', [{}])[0].get('type', 'Related')})")