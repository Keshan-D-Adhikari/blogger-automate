"""
Daily automatic price update, run by the dashboard server.

- Refreshes every post's price from the AliExpress API (same as Price Update -> Apply).
- Counts how many daily checks in a row a product was "not found". After
  UNAVAILABLE_DAYS checks it is listed as unavailable on the Price Update tab.
- With AUTO_DRAFT_UNAVAILABLE=true those posts are moved back to draft automatically.
  It is off by default: while the AliExpress app is in Test status, some products that
  are still on sale come back "not found".

.env:
  AUTO_PRICE_UPDATE=true
  UNAVAILABLE_DAYS=3
  AUTO_DRAFT_UNAVAILABLE=false
"""
import json
import os
import time

import publish as pw
import state_sync as sync
import update_prices as up

STATE_FILE = pw.STATE_DIR / "price_state.json"
ENABLED = os.getenv("AUTO_PRICE_UPDATE", "true").strip().lower() == "true"
UNAVAILABLE_DAYS = int(os.getenv("UNAVAILABLE_DAYS", "3"))
AUTO_DRAFT = os.getenv("AUTO_DRAFT_UNAVAILABLE", "false").strip().lower() == "true"
EVERY = 24 * 3600


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_run": 0, "missing": {}, "unavailable": {}, "last": None}


def save_state(st: dict):
    STATE_FILE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def due() -> bool:
    return ENABLED and time.time() - load_state()["last_run"] >= EVERY


def all_posts(svc):
    out, token = [], None
    while True:
        r = svc.posts().list(blogId=pw.BLOG_ID, maxResults=50, fetchBodies=True, pageToken=token,
                             status=["LIVE", "DRAFT"]).execute()
        out += r.get("items", [])
        token = r.get("nextPageToken")
        if not token:
            return out


def post_key(p) -> str:
    """The price key of a single-product post (empty for round-up posts with several products)."""
    boxes = list(up.BOX_RE.finditer(p.get("content", "")))
    if len(boxes) != 1:
        return ""
    keys = up.box_keys(boxes[0].group(0))
    return keys[0] if keys else ""


def run(svc, log=print) -> dict:
    def start():   # set first, so a crash doesn't retry in a loop
        st = load_state()
        st["last_run"] = time.time()
        save_state(st)
        return st
    st = sync.transact(start, "prices: start")
    posts = all_posts(svc)
    prices = up.fetch_prices(up.collect_keys(posts))
    changed = 0
    for p in posts:
        new_html, changes = up.update_content(p["content"], prices)
        if new_html != p["content"]:
            svc.posts().patch(blogId=pw.BLOG_ID, postId=p["id"], body={"content": new_html}).execute()
            changed += 1
            time.sleep(1)

    # unavailable tracking
    missing = st.get("missing", {})
    for key, info in prices.items():
        if info.get("notfound"):
            missing[key] = missing.get(key, 0) + 1
        elif "price" in info:
            missing.pop(key, None)
    unavailable = {}
    for p in posts:
        key = post_key(p)
        if not key or missing.get(key, 0) < UNAVAILABLE_DAYS:
            continue
        status = p.get("status")
        if AUTO_DRAFT and status == "LIVE":
            try:
                svc.posts().revert(blogId=pw.BLOG_ID, postId=p["id"]).execute()
                status = "DRAFT"
                log(f"moved to draft (unavailable): {p['title']}")
            except Exception as e:
                log(f"could not draft {p['title']}: {e}")
        unavailable[p["id"]] = {"title": p["title"], "url": p.get("url", ""), "status": status,
                                "days": missing[key]}
    last = {
        "time": time.time(), "posts": len(posts), "links": len(prices),
        "found": sum(1 for v in prices.values() if "price" in v), "changed": changed,
        "unavailable": len(unavailable),
    }

    def finish():
        cur = load_state()
        cur.update(missing=missing, unavailable=unavailable, last=last)
        save_state(cur)
    sync.transact(finish, "prices: done")
    return last


def mark_drafted(post_id: str):
    def op():
        st = load_state()
        if post_id in st.get("unavailable", {}):
            st["unavailable"][post_id]["status"] = "DRAFT"
            save_state(st)
    sync.transact(op, "prices: drafted")
