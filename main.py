from dotenv import load_dotenv
import os

load_dotenv()

anthropic_key = os.getenv("ANTHROPIC_API_KEY")
congress_key = os.getenv("CONGRESS_API_KEY")