"""
Pinterest API v5 helper: sign in (OAuth), list boards, create pins.

.env:
  PINTEREST_APP_ID=...
  PINTEREST_APP_SECRET=...
  PINTEREST_API=https://api.pinterest.com      # Trial access: https://api-sandbox.pinterest.com
  PINTEREST_ACCESS_TOKEN=pina_...              # optional: token from the app page, skips the OAuth login

The token is saved in pinterest_token.json (never commit it).
"""
import json
import os
import secrets
import time
import urllib.parse

import requests

from publish import ROOT

APP_ID = os.getenv("PINTEREST_APP_ID", "").strip()
APP_SECRET = os.getenv("PINTEREST_APP_SECRET", "").strip()
API = os.getenv("PINTEREST_API", "https://api.pinterest.com").strip().rstrip("/")
REDIRECT_URI = "http://localhost:5050/api/pinterest/callback"
SCOPES = "boards:read,pins:read,pins:write,user_accounts:read"
STATIC_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN", "").strip()
TOKEN_FILE = ROOT / "pinterest_token.json"
_state = {"value": ""}


def configured() -> bool:
    return bool(STATIC_TOKEN or (APP_ID and APP_SECRET))


def connected() -> bool:
    return bool(STATIC_TOKEN) or TOKEN_FILE.exists()


def auth_url() -> str:
    _state["value"] = secrets.token_urlsafe(16)
    q = urllib.parse.urlencode({
        "client_id": APP_ID, "redirect_uri": REDIRECT_URI, "response_type": "code",
        "scope": SCOPES, "state": _state["value"],
    })
    return f"https://www.pinterest.com/oauth/?{q}"


def _token_request(data: dict) -> dict:
    r = requests.post(f"{API}/v5/oauth/token", data=data, auth=(APP_ID, APP_SECRET), timeout=30)
    if not r.ok:
        raise RuntimeError(f"Pinterest token error {r.status_code}: {r.text[:200]}")
    tok = r.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 0) - 60
    old = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
    tok.setdefault("refresh_token", old.get("refresh_token"))
    TOKEN_FILE.write_text(json.dumps(tok, indent=1), encoding="utf-8")
    return tok


def finish_login(code: str, state: str):
    if not state or state != _state["value"]:
        raise RuntimeError("Login state mismatch. Click Connect Pinterest again.")
    _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})


def _access_token() -> str:
    if STATIC_TOKEN:
        return STATIC_TOKEN
    if not TOKEN_FILE.exists():
        raise RuntimeError("Pinterest is not connected.")
    tok = json.loads(TOKEN_FILE.read_text())
    if tok.get("expires_at", 0) < time.time() and tok.get("refresh_token"):
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    return tok["access_token"]


def _call(method: str, path: str, **kw) -> dict:
    r = requests.request(method, f"{API}/v5{path}", timeout=30,
                         headers={"Authorization": f"Bearer {_access_token()}"}, **kw)
    if not r.ok:
        raise RuntimeError(f"Pinterest {r.status_code}: {r.text[:200]}")
    return r.json()


def boards() -> list[dict]:
    out, bookmark = [], None
    while True:
        params = {"page_size": 100, **({"bookmark": bookmark} if bookmark else {})}
        r = _call("GET", "/boards", params=params)
        out += [{"id": b["id"], "name": b["name"]} for b in r.get("items", [])]
        bookmark = r.get("bookmark")
        if not bookmark:
            return out


def create_pin(board_id: str, title: str, image: str, link: str, price: float = 0) -> str:
    name = title.split(":")[0].strip()
    desc = f"{name} for around ${price:.2f} on AliExpress. A budget find worth checking out! " if price else f"{name}. A budget find worth checking out! "
    desc += "#budgetfinds #aliexpressfinds #deals #amazingfinds"
    pin = _call("POST", "/pins", json={
        "board_id": board_id,
        "title": name[:100],
        "description": desc[:500],
        "link": link,
        "alt_text": name[:500],
        "media_source": {"source_type": "image_url", "url": image},
    })
    return f"https://www.pinterest.com/pin/{pin['id']}/"
