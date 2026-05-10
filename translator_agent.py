import anthropic
import os
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

# State context for personalization
STATE_CONTEXT = {
    "VT": "a small, rural New England state known for agriculture, dairy farming, and skiing",
    "CA": "the most populous state with a large tech industry, agriculture, and diverse urban centers",
    "NY": "home to New York City, major financial and media industries, and large rural upstate areas",
    "TX": "a large state with major oil and gas industry, agriculture, and rapidly growing cities",
    "FL": "home to many retirees, tourism, and a large Latino population",
    "OH": "a Midwest manufacturing state with major automotive and steel industries",
    "PA": "a mix of major cities and rural communities with manufacturing and energy industries",
    "IL": "home to Chicago, a major financial center, and large agricultural regions",
    "GA": "a Southern state with major agricultural and logistics industries",
    "WA": "home to major tech companies and a large aerospace industry",
    "MI": "center of the American auto industry with major manufacturing",
    "AZ": "a fast-growing Sun Belt state with large retirement and Latino communities",
    "NC": "a mix of research, manufacturing, agriculture, and military bases",
    "VA": "home to many federal workers, military bases, and tech companies",
    "MA": "home to major universities, biotech, and healthcare industries",
    "CO": "known for outdoor recreation, energy, and a growing tech sector",
    "MN": "a Midwest state with healthcare, agriculture, and manufacturing",
    "OR": "known for tech, timber, agriculture, and outdoor recreation",
    "WI": "a Midwest state with dairy farming, manufacturing, and tourism",
    "NV": "known for tourism, gaming, and a growing tech sector",
}

def translate_bill(bill_data, client, user_context=None):
    bill = bill_data["bill"]
    
    title = bill.get("title", "Unknown")
    sponsors = bill.get("sponsors", [{}])
    sponsor = sponsors[0].get("fullName", "Unknown") if sponsors else "Unknown"
    status = bill.get("latestAction", {}).get("text", "Unknown")
    policy_area = bill.get("policyArea", {}).get("name", "")
    
    # Build personalization context
    personalization = ""
    if user_context:
        state = user_context.get("state", "")
        interests = user_context.get("interests", [])
        state_desc = STATE_CONTEXT.get(state, f"the state of {state}")
        
        if state or interests:
            personalization = f"""
Personalization context (use this to make the explanation more relevant):
- The reader lives in {state_desc if state else 'the United States'}
- They care about: {', '.join(interests) if interests else 'general civic issues'}

Make the explanation relevant to their context where applicable:
- Mention specific impacts on their state if relevant
- Connect to their stated interests naturally
- Do NOT assume their political views
- Do NOT frame the bill politically based on their interests
- DO explain practical real-world impacts for someone in their situation
"""

    prompt = f"""
You are a plain English translator for legislation.
Your only job is to explain a bill clearly to an average person.
No legal jargon. No assumptions about their background.
Be concise but complete.

{personalization}

Bill Title: {title}
Sponsor: {sponsor}
Current Status: {status}
Policy Area: {policy_area}

Explain:
1. What this bill is in one sentence
2. Who it affects and how — be specific to the reader's context if personalization is provided
3. What it means that it has reached this status
"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    translation = message.content[0].text

    log_action(
        agent_name="translator",
        action="translate_bill",
        input_data={
            "title": title,
            "sponsor": sponsor,
            "personalized": user_context is not None
        },
        output_data={"translation_preview": translation[:100]}
    )

    return translation


if __name__ == "__main__":
    from bill_fetcher import fetch_bill

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    bill_data = fetch_bill(111, "hr", 3590)

    print("WITHOUT CONTEXT:")
    print("-" * 40)
    print(translate_bill(bill_data, client))
    print()

    print("WITH VERMONT FARMER CONTEXT:")
    print("-" * 40)
    context = {
        "state": "VT",
        "interests": ["healthcare", "agriculture"]
    }
    print(translate_bill(bill_data, client, user_context=context))
    print()

    print("WITH FLORIDA RETIREE CONTEXT:")
    print("-" * 40)
    context = {
        "state": "FL",
        "interests": ["healthcare", "economy"]
    }
    print(translate_bill(bill_data, client, user_context=context))