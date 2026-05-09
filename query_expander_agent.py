import anthropic
import os
import json
from dotenv import load_dotenv
from documentor_agent import log_action

load_dotenv()

KNOWN_ACRONYMS = {
    "genius act": "Guiding and Establishing National Innovation for US Stablecoins",
    "cara": "Comprehensive Addiction and Recovery Act",
    "aca": "Affordable Care Act",
    "chips act": "Creating Helpful Incentives to Produce Semiconductors",
    "fisa": "Foreign Intelligence Surveillance Act",
    "ndaa": "National Defense Authorization Act",
    "vawa": "Violence Against Women Act",
    "essa": "Every Student Succeeds Act",
    "snap": "Supplemental Nutrition Assistance Program",
    "tanf": "Temporary Assistance for Needy Families",
}

def expand_query(keywords, topic, client):
    # Check for known acronyms first
    topic_lower = topic.lower()
    for acronym, full_name in KNOWN_ACRONYMS.items():
        if acronym in topic_lower:
            # Add the full name to keywords before AI expansion
            keywords = keywords + [full_name]
            break
    """
    Takes router keywords and expands them into legislative vocabulary.
    Returns 5-7 specific terms that GovInfo will find relevant bills for.
    """
    
    if not keywords:
        return keywords
    
    prompt = f"""
    You are a legislative search specialist.
    Your only job is to expand plain English search terms into official legislative vocabulary.
    
    User is searching for: {topic}
    Initial keywords: {keywords}
    
    Return ONLY valid JSON, no markdown, no explanation.
    
    Rules:
    - Generate 5-7 specific legislative terms
    - Include official bill names, acronyms, and technical terms used in legislation
    - Include related medical, legal, or policy terminology Congress actually uses
    - NEVER include generic words like: bill, law, act, congress, legislation, federal, policy
    - Terms should be specific enough to find relevant bills but not so narrow they miss things
    
    Examples:
    "opioid epidemic" → ["opioid", "fentanyl", "naloxone", "substance use disorder", "overdose", "CARA", "addiction treatment"]
    "climate change" → ["greenhouse gas", "carbon emissions", "clean energy", "climate", "renewable", "Paris Agreement", "EPA"]
    "student loans" → ["student loan", "higher education", "loan forgiveness", "FAFSA", "Pell Grant", "tuition", "college debt"]
    "gun control" → ["firearm", "background check", "assault weapon", "gun violence", "Second Amendment", "ATF", "concealed carry"]
    "healthcare" → ["Affordable Care Act", "Medicaid", "Medicare", "insurance coverage", "preexisting condition", "ACA", "public option"]
    
    Return ONLY this JSON:
    {{
        "expanded_terms": ["term1", "term2", "term3", "term4", "term5"]
    }}
    """
    
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    
    try:
        result = json.loads(raw)
        expanded = result.get("expanded_terms", keywords)
    except json.JSONDecodeError:
        expanded = keywords
    
    log_action(
        agent_name="query_expander",
        action="expand_query",
        input_data={"keywords": keywords, "topic": topic},
        output_data={"expanded_terms": expanded}
    )
    
    return expanded

if __name__ == "__main__":
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    tests = [
        (["opioid", "epidemic"], "opioid epidemic legislation"),
        (["climate", "change"], "climate change bills"),
        (["gun", "control"], "gun control legislation"),
        (["student", "loans"], "student loan bills"),
    ]
    
    print("QUERY EXPANDER TEST")
    print("-" * 40)
    
    for keywords, topic in tests:
        expanded = expand_query(keywords, topic, client)
        print(f"Input:    {keywords}")
        print(f"Expanded: {expanded}")
        print()