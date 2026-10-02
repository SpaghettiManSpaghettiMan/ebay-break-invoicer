"""
eBay Sandbox Token Setup
========================
One-time OAuth flow to get refresh tokens for all 6 Sandbox accounts.
Opens each login in a new browser tab. After you log in and authorize,
you paste the full redirect URL from your browser back into the terminal.
Saves all tokens to sandbox_tokens.json.

Requirements:
    pip install requests

Run:
    python3 ebay_sandbox_setup_tokens.py
"""

import json
import os
import time
import webbrowser
import secrets
import urllib.parse
import base64
import requests

# =============================================================================
# CONFIGURATION — loaded from sandbox_keys.json
# =============================================================================

KEYS_FILE = "sandbox_keys.json"

def load_keys():
    if not os.path.exists(KEYS_FILE):
        print(f"❌ {KEYS_FILE} not found.")
        print(f'   Create it with: {{"client_id": "...", "client_secret": "...", "ru_name": "..."}}')
        raise SystemExit(1)
    with open(KEYS_FILE) as f:
        keys = json.load(f)
    missing = [k for k in ["client_id", "client_secret", "ru_name"] if not keys.get(k)]
    if missing:
        print(f"❌ Missing keys in {KEYS_FILE}: {', '.join(missing)}")
        raise SystemExit(1)
    return keys

_keys         = load_keys()
CLIENT_ID     = _keys["client_id"]
CLIENT_SECRET = _keys["client_secret"]
RU_NAME       = _keys["ru_name"]

SANDBOX_AUTH_BASE = "https://auth.sandbox.ebay.com/oauth2/authorize"
SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
])

ACCOUNTS = [
    {"name": "SELLER",                 "label": "your Sandbox SELLER account (Bob)"},
    {"name": "Jack98765432345678987",  "label": "TESTUSER_Jack98765432345678987"},
    {"name": "Thom98765432345678987",  "label": "TESTUSER_Thom98765432345678987"},
    {"name": "Jim98765432345678987",   "label": "TESTUSER_Jim98765432345678987"},
    {"name": "Dirk98765432345678987",  "label": "TESTUSER_Dirk98765432345678987"},
    {"name": "Helen98765432345678987",    "label": "TESTUSER_Helen98765432345678987"},
    {"name": "Ish987654323456789876",      "label": "TESTUSER_Ish987654323456789876"},
    {"name": "Francois987654323456789876", "label": "TESTUSER_Francois987654323456789876"},
]

TOKENS_FILE = "sandbox_tokens.json"

# =============================================================================
# OAUTH HELPERS
# =============================================================================

def get_auth_url():
    params = {
        "client_id":     CLIENT_ID,
        "redirect_uri":  RU_NAME,
        "response_type": "code",
        "scope":         SCOPES,
        "state":         secrets.token_hex(8),
    }
    return f"{SANDBOX_AUTH_BASE}?{urllib.parse.urlencode(params)}"


def extract_code_from_url(url):
    """Pull the auth code out of the redirect URL the user pastes in."""
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            return urllib.parse.unquote(code)
    except Exception:
        pass
    return None


def exchange_code_for_token(auth_code):
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    resp = requests.post(
        SANDBOX_TOKEN_URL,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":   "authorization_code",
            "code":         auth_code,
            "redirect_uri": RU_NAME,
        },
    )
    return resp.json()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n🔐 eBay Sandbox Token Setup")
    print("=" * 55)
    print(f"  Accounts to authorize: {len(ACCOUNTS)}")
    print(f"  Tokens saved to:       {TOKENS_FILE}")
    print()
    print("  HOW THIS WORKS:")
    print("  ───────────────")
    print("  1. A browser tab opens with the eBay Sandbox login")
    print("  2. Log in as the account shown, click Agree/Allow")
    print("  3. eBay redirects to a page — copy the FULL URL from")
    print("     your browser address bar and paste it here")
    print("  4. Repeat for all 6 accounts")
    print()
    input("  Press Enter to begin...")

    # Load existing tokens
    tokens = {}
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            tokens = json.load(f)
        print(f"\n  Found existing tokens for: {', '.join(tokens.keys())}")

    browser = webbrowser.get()

    for i, account in enumerate(ACCOUNTS):
        name  = account["name"]
        label = account["label"]

        if name in tokens:
            print(f"\n  ⏭️  Skipping {name} — already authorized")
            continue

        print(f"\n{'─' * 55}")
        print(f"  Account {i+1}/{len(ACCOUNTS)}: {label}")
        print(f"{'─' * 55}")
        print(f"  Make sure you are logged OUT of any other eBay account")
        print(f"  in your browser before proceeding.")
        input(f"  Press Enter to open the login page...")

        auth_url = get_auth_url()
        if i == 0:
            browser.open_new(auth_url)
        else:
            browser.open_new_tab(auth_url)

        print()
        print(f"  ✋ Log in as: {label}")
        print(f"  ✋ Click Agree/Allow on the authorization screen")
        print(f"  ✋ When redirected, COPY the full URL from your browser")
        print()

        while True:
            pasted = input("  Paste the full redirect URL here: ").strip()

            if not pasted:
                print("  ⚠️  Nothing pasted. Try again.")
                continue

            code = extract_code_from_url(pasted)

            if not code:
                print("  ⚠️  Couldn't find auth code in that URL.")
                retry = input("  Try again? (yes/no): ").strip().lower()
                if retry != "yes":
                    print(f"  Skipping {name}.")
                    break
                continue

            print(f"  ✅ Code found! Exchanging for token...")
            token_data = exchange_code_for_token(code)

            refresh_token = token_data.get("refresh_token")
            access_token  = token_data.get("access_token")
            error         = token_data.get("error_description", token_data.get("error"))

            if refresh_token:
                tokens[name] = {
                    "refresh_token": refresh_token,
                    "access_token":  access_token,
                    "label":         label,
                    "authorized_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                with open(TOKENS_FILE, "w") as f:
                    json.dump(tokens, f, indent=2)
                print(f"  💾 Token saved for {name}")
                break
            else:
                print(f"  ❌ Token exchange failed: {error}")
                print(f"     The code may have expired (~5 min limit).")
                retry = input("  Retry this account? (yes/no): ").strip().lower()
                if retry == "yes":
                    auth_url = get_auth_url()
                    browser.open_new_tab(auth_url)
                    print(f"  New tab opened. Authorize and paste the new URL.")
                    continue
                break

        time.sleep(0.5)

    print(f"\n{'=' * 55}")
    authorized = len(tokens)
    print(f"  ✅ {authorized}/{len(ACCOUNTS)} accounts authorized")
    if authorized < len(ACCOUNTS):
        skipped = [a["name"] for a in ACCOUNTS if a["name"] not in tokens]
        print(f"  ⚠️  Missing: {', '.join(skipped)}")
        print(f"     Re-run this script to finish — done ones are skipped.")
    print(f"  Tokens saved → {TOKENS_FILE}")
    print(f"\n  Next step: python3 ebay_sandbox_simulator.py")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    main()
