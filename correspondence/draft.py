from .gmail import FOOTER


def generate_draft(
    bill_id, bill_title, bill_summary, latest_action,
    legislator_name, legislator_office,
    city, state, user_statement, full_name, claude_client
) -> str:
    msg = claude_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": (
                "You are helping a constituent write a letter to their representative.\n"
                "Write a concise, respectful letter (200-300 words).\n\n"
                "STRICT RULES:\n"
                "- Only use personal details the constituent explicitly stated. Do NOT infer, invent, or add any details about their job, family, income, health, or situation that they did not directly say.\n"
                "- If their statement is vague, keep the letter vague in the same way. Never fill in specifics they didn't provide.\n"
                "- Quote or closely paraphrase their words when describing personal impact. Do not upgrade or dramatize.\n"
                "- No advocacy boilerplate or campaign language.\n"
                "- No signature line — the sender's name comes from their email address.\n\n"
                "Structure:\n"
                "1. Brief opener: constituent's location only (city, state)\n"
                "2. Reference the bill by name and number\n"
                "3. Personal impact — only what the constituent actually said\n"
                "4. Specific ask (support / oppose / clarify position)\n"
                "5. Request for a response\n\n"
                f"Bill: {bill_title} ({bill_id})\n"
                f"Status: {latest_action or 'Active'}\n"
                f"Summary: {bill_summary}\n"
                f"Constituent name: {full_name}\n"
                f"What the constituent said (use only this — nothing more): \"{user_statement}\"\n"
                f"Legislator: {legislator_name}, {legislator_office}\n"
                f"Constituent location: {city}, {state}"
            )
        }]
    )
    return msg.content[0].text.strip()


def moderate_email(body: str, bill_id: str, claude_client) -> tuple[bool, str]:
    """
    Content-check the email body before sending.
    Returns (approved, reason).
    """
    msg = claude_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": (
                f"Review this email intended for a US elected official regarding bill {bill_id}.\n"
                "BLOCK it if it contains: threats, harassment, hate speech, personal attacks,\n"
                "or coordinated campaign/bot language.\n"
                "APPROVE: opinions, policy criticism, requests to support/oppose a bill, emotional appeals.\n\n"
                f"Email body:\n---\n{body[:2000]}\n---\n\n"
                "Reply with exactly APPROVED or BLOCKED, then a space, then one short reason."
            )
        }]
    )
    text = msg.content[0].text.strip()
    ok = text.upper().startswith("APPROVED")
    reason = text[len("BLOCKED"):].strip() if not ok else ""
    return ok, reason


def generate_followup(original_body: str, reply_text: str, legislator_name: str, claude_client) -> str:
    msg = claude_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": (
                f"Help a constituent write a follow-up letter to {legislator_name}.\n\n"
                f"Original letter:\n---\n{original_body[:1000]}\n---\n\n"
                f"Representative's reply:\n---\n{reply_text[:1000]}\n---\n\n"
                "Write a polite follow-up (100-200 words) that acknowledges their response "
                "and continues the conversation. Be respectful and specific.\n"
                "Do not invent any new personal details beyond what the original letter stated.\n"
                "Do not add a signature line."
            )
        }]
    )
    return msg.content[0].text.strip()
