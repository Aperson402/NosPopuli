import anthropic
import os
from dotenv import load_dotenv
from bill_fetcher import fetch_bill
from documentor_agent import log_action

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def translate_bill(bill_data, client):
    bill = bill_data["bill"]
    
    title = bill["title"]
    sponsor = bill["sponsors"][0]["fullName"]
    status = bill["latestAction"]["text"]
    
    prompt = f"""
    You are a plain English translator for legislation.
    Your only job is to explain a bill clearly to an average person.
    No legal jargon. No assumptions about their background.
    Be concise but complete.
    
    Bill Title: {title}
    Sponsor: {sponsor}
    Current Status: {status}
    
    Explain:
    1. What this bill is in one sentence
    2. Who it affects and how
    3. What it means that it became law
    """
    
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    translation = message.content[0].text
    
    log_action(
        agent_name="translator",
        action="translate_bill",
        input_data={
            "title": title,
            "sponsor": sponsor
        },
        output_data={
            "translation_preview": translation[:100]
        }
    )
    
    return translation

if __name__ == "__main__":
    bill_data = fetch_bill(111, "hr", 3590)
    
    if bill_data:
        print("TRANSLATOR AGENT - Plain English Output:")
        print("-" * 40)
        translation = translate_bill(bill_data)
        print(translation)