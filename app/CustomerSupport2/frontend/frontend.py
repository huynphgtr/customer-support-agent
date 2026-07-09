"""Flask frontend for Customer Support Agent with Cognito authentication."""

import base64
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "workshop-agentcore-dev-secret-key-do-not-use-in-prod"

# --- Configuration ---
REGION = "us-east-1"
COGNITO_DOMAIN = "workshop-agentcore-cs2"
COGNITO_POOL_ID = "us-east-1_ZxJksP0QJ"
CLIENT_ID = "46qmrju8pqjnn563k9rdmv3gp3"  # Web client (public, no secret)
REDIRECT_URI = "http://localhost:8501/callback"
COGNITO_BASE_URL = f"https://{COGNITO_DOMAIN}.auth.{REGION}.amazoncognito.com"


def get_runtime_arn() -> str:
    """Read runtime ARN from deployed-state.json"""
    state_path = Path(__file__).resolve().parents[3] / "agentcore" / ".cli" / "deployed-state.json"
    with open(state_path) as f:
        state = json.load(f)
    runtimes = state["targets"]["default"]["resources"]["runtimes"]
    first_runtime = next(iter(runtimes.values()))
    return first_runtime["runtimeArn"]


RUNTIME_ARN = get_runtime_arn()
ENCODED_ARN = quote(RUNTIME_ARN, safe="")
INVOKE_URL = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations"

print(f"Runtime ARN: {RUNTIME_ARN}")


# --- PKCE helpers ---

def generate_code_verifier() -> str:
    """Generate a random code verifier for PKCE"""
    return secrets.token_urlsafe(64)[:128]


def generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from verifier"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def get_login_url(code_challenge: str):
    """Build Cognito hosted UI login URL with PKCE"""
    return (
        f"{COGNITO_BASE_URL}/login?"
        f"client_id={CLIENT_ID}&"
        f"response_type=code&"
        f"scope=openid+email+profile&"
        f"redirect_uri={REDIRECT_URI}&"
        f"code_challenge_method=S256&"
        f"code_challenge={code_challenge}"
    )


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for tokens using PKCE"""
    token_url = f"{COGNITO_BASE_URL}/oauth2/token"
    resp = requests.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()


def invoke_agent(prompt: str, session_id: str, access_token: str) -> str:
    """Call AgentCore Runtime with bearer token"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "x-amzn-bedrock-agentcore-session-id": session_id,
    }
    payload = json.dumps({"prompt": prompt})

    resp = requests.post(INVOKE_URL, headers=headers, data=payload)

    if resp.status_code == 401:
        return "ERROR:AUTH_EXPIRED"
    resp.raise_for_status()

    # Parse SSE response - each line is "data: <content>"
    full_response = ""
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data = line[6:]
            # Remove surrounding quotes if present
            if data.startswith('"') and data.endswith('"'):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    data = data[1:-1]
            # Check for error objects
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict) and "error" in parsed:
                    return f"Error: {parsed['error']}"
            except (json.JSONDecodeError, TypeError):
                pass
            if isinstance(data, str):
                full_response += data

    return full_response if full_response else resp.text


# --- Routes ---

@app.route("/")
def index():
    if "access_token" not in session:
        # Generate PKCE verifier and store in session
        code_verifier = generate_code_verifier()
        session["code_verifier"] = code_verifier
        code_challenge = generate_code_challenge(code_verifier)
        return render_template("login.html", login_url=get_login_url(code_challenge))
    return render_template(
        "index.html",
        runtime_arn=RUNTIME_ARN.split("/")[-1][:40],
        username=session.get("username", "User"),
    )


@app.route("/callback")
def callback():
    """Handle Cognito OAuth callback with PKCE"""
    code = request.args.get("code")
    if not code:
        return redirect(url_for("index"))

    code_verifier = session.get("code_verifier")
    if not code_verifier:
        print("No code_verifier in session")
        return redirect(url_for("index"))

    try:
        tokens = exchange_code_for_tokens(code, code_verifier)
        session["access_token"] = tokens["access_token"]
        session.pop("code_verifier", None)

        # Decode username from token (no verification needed - Cognito already validated)
        import jwt
        claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        session["username"] = claims.get("username", claims.get("email", "User"))
    except Exception as e:
        print(f"Auth error: {e}")
        return redirect(url_for("index"))

    return redirect(url_for("index"))


@app.route("/chat", methods=["POST"])
def chat():
    """Chat endpoint - proxies to AgentCore Runtime"""
    if "access_token" not in session:
        return {"error": "Not authenticated"}, 401

    data = request.json
    prompt = data.get("prompt", "")
    session_id = data.get("session_id", str(uuid.uuid4()))

    try:
        response = invoke_agent(prompt, session_id, session["access_token"])
        if response == "ERROR:AUTH_EXPIRED":
            session.clear()
            return {"error": "Session expired. Please login again."}, 401
        return {"response": response}
    except Exception as e:
        print(f"Invoke error: {e}")
        return {"error": str(e)}, 500


@app.route("/logout")
def logout():
    """Clear session and redirect to Cognito logout"""
    session.clear()
    logout_url = (
        f"{COGNITO_BASE_URL}/logout?"
        f"client_id={CLIENT_ID}&"
        f"logout_uri=http://localhost:8501/"
    )
    return redirect(logout_url)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8501, debug=False)
