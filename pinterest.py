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

import state_sync as sync
from publish import ROOT, STATE_DIR

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


def create_pin(board_id: str, title: str, image: str, link: str, price: float = 0,
               rating: float = 0, labels=None) -> str:
    import base64
    from pin_image import make_pin
    name = title.split(":")[0].strip()
    desc = f"{name} for around ${price:.2f} on AliExpress. A budget find worth checking out! " if price else f"{name}. A budget find worth checking out! "
    desc += "#budgetfinds #aliexpressfinds #deals #amazingfinds"
    png = make_pin(title, image, price, rating, labels)
    pin = _call("POST", "/pins", json={
        "board_id": board_id,
        "title": name[:100],
        "description": desc[:500],
        "link": link,
        "alt_text": name[:500],
        "media_source": {"source_type": "image_base64", "content_type": "image/png",
                         "data": base64.b64encode(png).decode()},
    })
    return f"https://www.pinterest.com/pin/{pin['id']}/"


# ---------------------------------------------------------------- pin queue
# Pins are spaced out (PIN_INTERVAL_MIN, default 90) so Pinterest doesn't see a burst.
# Shared with the GitHub Actions job like the post queue: claim (pinning) -> finish.
QUEUE_FILE = STATE_DIR / "pin_queue.json"
INTERVAL = int(os.getenv("PIN_INTERVAL_MIN", "90")) * 60


def load_queue() -> list[dict]:
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8")) if QUEUE_FILE.exists() else []


def save_queue(q: list[dict]):
    QUEUE_FILE.write_text(json.dumps(q, indent=1), encoding="utf-8")


def enqueue(board_id: str, title: str, image: str, link: str, price: float = 0,
            rating: float = 0, labels=None) -> float:
    def op():
        q = load_queue()
        pending = [x["due"] for x in q if x["status"] in ("queued", "pinning")]
        last_done = max([x.get("done_at", 0) for x in q if x["status"] == "pinned"], default=0)
        due = max(time.time(), (max(pending) if pending else last_done) + INTERVAL)
        q.append({"board": board_id, "title": title, "image": image, "link": link, "price": price,
                  "rating": rating, "labels": labels or [], "due": due, "status": "queued"})
        save_queue(q)
        return due
    return sync.transact(op, "pins: add")


def run_due():
    """Pin at most one due item."""
    def claim():
        q = load_queue()
        for x in q:
            if x["status"] == "pinning" and time.time() - x.get("claimed_at", 0) > 30 * 60:
                x.update(status="queued", due=time.time())   # interrupted: try again
        item = next((x for x in q if x["status"] == "queued" and x["due"] <= time.time()), None)
        if item:
            item.update(status="pinning", claimed_at=time.time())
        save_queue(q)
        return dict(item) if item else None
    item = sync.transact(claim, "pins: claim")
    if not item:
        return
    try:
        pin, err = create_pin(item["board"], item["title"], item["image"], item["link"],
                              item["price"], item["rating"], item["labels"]), ""
    except Exception as e:
        pin, err = "", str(e)[:200]

    def finish():
        q = load_queue()
        x = next((x for x in q if x["status"] == "pinning" and x["link"] == item["link"]
                  and x.get("claimed_at") == item["claimed_at"]), None)
        if not x:
            return
        if pin:
            x.update(pin=pin, status="pinned", done_at=time.time())
        else:
            x["tries"] = x.get("tries", 0) + 1
            x["error"] = err
            x.update(status="failed" if x["tries"] >= 3 else "queued", due=time.time() + 15 * 60)
        save_queue(q)
    sync.transact(finish, "pins: " + ("pinned" if pin else "retry"))
