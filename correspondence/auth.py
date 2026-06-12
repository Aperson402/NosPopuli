import os
import hashlib
import secrets
from datetime import datetime, timedelta

# Allow OAuth over plain HTTP for localhost dev
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from google_auth_oauthlib.flow import Flow
from jose import jwt, JWTError

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
JWT_SECRET           = os.getenv("JWT_SECRET") or secrets.token_hex(32)
JWT_ALGORITHM        = "HS256"
JWT_EXPIRE_DAYS      = 30
BASE_URL             = os.getenv("BASE_URL", "http://localhost:8000")
REDIRECT_URI         = f"{BASE_URL}/auth/google/callback"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Store the Flow object per state so PKCE code_verifier is preserved
_pending_flows: dict[str, object] = {}


def _build_flow():
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )


def get_auth_url():
    """Returns (auth_url, state) to redirect the browser to Google."""
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    _pending_flows[state] = flow  # preserve flow so PKCE verifier survives
    return auth_url, state


def exchange_code(code, state):
    """
    Exchange authorization code → (id_info dict, refresh_token str).
    Raises ValueError on bad state.
    """
    if state not in _pending_flows:
        raise ValueError("Invalid OAuth state — server may have restarted mid-flow")
    flow = _pending_flows.pop(state)

    flow.fetch_token(code=code)

    credentials = flow.credentials

    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests

    id_info = id_token.verify_oauth2_token(
        credentials.id_token,
        google_requests.Request(),
        GOOGLE_CLIENT_ID,
    )

    return id_info, credentials.refresh_token


def make_user_id(google_sub: str) -> str:
    return hashlib.sha256(f"google:{google_sub}".encode()).hexdigest()[:32]


def issue_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> str:
    """Returns user_id or raises ValueError."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")
