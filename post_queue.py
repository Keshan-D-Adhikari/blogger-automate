"""
Post queue for bulk imports: products found with search are posted to Blogger a few
at a time, so the blog doesn't get hundreds of posts in one go (Blogger may flag it as spam).

.env:
  POST_INTERVAL_MIN=20    # minutes between posts
  DAILY_POST_LIMIT=25     # max posts in any 24 hours

The queue can be shared by the laptop and the GitHub Actions job (state_sync.py), so a post
is "claimed" (status posting) and saved before it goes to Blogger, then "finished".
That way two machines never post the same product.
"""
import json
import os
import time

import publish as pw
import state_sync as sync

QUEUE_FILE = pw.STATE_DIR / "post_queue.json"
INTERVAL = int(os.getenv("POST_INTERVAL_MIN", "20")) * 60
DAILY_LIMIT = int(os.getenv("DAILY_POST_LIMIT", "25"))
STALE = 30 * 60   # a claim older than this was interrupted


def load() -> list[dict]:
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8")) if QUEUE_FILE.exists() else []


def save(q: list[dict]):
    QUEUE_FILE.write_text(json.dumps(q, indent=1), encoding="utf-8")


def product_key(pid) -> str:
    return f"id:{pid}"


def _pid(x) -> str:
    return str(x["product"]["product_id"])


def queued_ids() -> set:
    return {_pid(x) for x in load() if x["status"] in ("queued", "posting", "posted")}


def add(products: list[dict], publish: bool, board: str = "") -> int:
    def op():
        q = load()
        have = {_pid(x) for x in q if x["status"] in ("queued", "posting", "posted")}
        have |= {k[3:] for k in pw.load_done() if k.startswith("id:")}
        added = 0
        for p in products:
            pid = str(p["product_id"])
            if pid in have:
                continue
            q.append({"product": p, "labels": p.get("_labels", []), "title": p.get("_title", ""),
                      "publish": publish, "board": board, "status": "queued", "added": time.time()})
            have.add(pid)
            added += 1
        save(q)
        return added
    return sync.transact(op, f"queue: add {len(products)} products")


def posted_last_day(q) -> int:
    return sum(1 for x in q if x["status"] in ("posted", "posting") and
               x.get("done_at", x.get("claimed_at", 0)) > time.time() - 86400)


def next_time(q) -> float:
    last = max([x.get("done_at", x.get("claimed_at", 0)) for x in q
                if x["status"] in ("posted", "failed", "posting")], default=0)
    return last + INTERVAL


def _expire_stale(q):
    for x in q:
        if x["status"] == "posting" and time.time() - x.get("claimed_at", 0) > STALE:
            if x.get("tries", 0) + 1 < MAX_TRIES:   # the next try checks the blog first
                x.update(status="queued", tries=x.get("tries", 0) + 1, error="Interrupted while posting.")
            else:
                x.update(status="failed", done_at=time.time(),
                         error="Interrupted while posting. Check the blog before adding it again.")


def _claim(pid: str = "") -> dict | None:
    """Mark the next due product (or a given one) as posting and save that first."""
    def op():
        q = load()
        _expire_stale(q)
        if pid:
            item = next((x for x in q if x["status"] == "queued" and _pid(x) == pid), None)
        else:
            item = next((x for x in q if x["status"] == "queued"), None)
            if item and (time.time() < next_time(q) or posted_last_day(q) >= DAILY_LIMIT):
                item = None
        if item:
            item.update(status="posting", claimed_at=time.time())
        save(q)
        return dict(item) if item else None
    return sync.transact(op, f"queue: posting {pid or 'next'}")


def _finish(pid: str, url: str = "", error: str = "", retry: bool = False):
    def op():
        q = load()
        item = next((x for x in q if x["status"] == "posting" and _pid(x) == pid), None)
        if item:
            if retry:
                # network hiccup: back to the queue, checked against the blog before the next try
                item.update(status="queued", tries=item.get("tries", 0) + 1, error=error[:200])
            else:
                item.update(status="posted" if url else "failed", done_at=time.time())
                if url:
                    item["url"] = url
                else:
                    item["error"] = error[:200]
            save(q)
        if url:
            done = pw.load_done()
            done[product_key(pid)] = url
            pw.DONE_FILE.write_text(json.dumps(done, indent=1), encoding="utf-8")
    sync.transact(op, f"queue: {'posted' if url else 'retry' if retry else 'failed'} {pid}")


MAX_TRIES = 3


def _transient(e: Exception) -> bool:
    """Network errors (SSL EOF, timeouts, Google 5xx/429) are worth another try."""
    import httplib2
    from googleapiclient.errors import HttpError
    if isinstance(e, HttpError):
        return e.resp.status >= 500 or e.resp.status == 429
    return isinstance(e, (OSError, httplib2.HttpLib2Error))


def _already_on_blog(blogger, title: str) -> str:
    """URL of a recent post with this title: an earlier try may have reached Blogger before the error."""
    r = blogger.posts().list(blogId=pw.BLOG_ID, maxResults=25, fetchBodies=False, orderBy="UPDATED",
                             status=["LIVE", "DRAFT"]).execute()
    for p in r.get("items", []):
        if p.get("title") == title:
            return p.get("url") or f"draft id {p.get('id')}"
    return ""


def _fresh(p: dict) -> dict:
    """Today's price and stats; the queued copy can be days old. Falls back to the queued copy."""
    try:
        return {**p, **pw.get_product(str(p["product_id"]))}
    except Exception as e:
        print("product refresh failed, using queued data:", str(e)[:120])
        return p


def _post(item: dict, blogger, on_posted=None) -> dict:
    pid = _pid(item)
    p = _fresh(item["product"])
    item = {**item, "product": p}
    try:
        problems = pw.quality_check(p)
        if problems:
            raise RuntimeError("Quality filter: " + ", ".join(problems))
        post = pw.build_post(p, item["labels"])
        if item.get("title"):
            post["title"] = item["title"][:140]
        url = _already_on_blog(blogger, post["title"]) if item.get("tries") else ""
        if not url:
            url = pw.blogger_post(blogger, post, item["publish"])
    except Exception as e:
        if _transient(e) and item.get("tries", 0) + 1 < MAX_TRIES:
            _finish(pid, error=str(e), retry=True)
            return {**item, "status": "queued", "error": str(e)[:200]}
        _finish(pid, error=str(e))
        return {**item, "status": "failed", "error": str(e)[:200]}
    _finish(pid, url=url)
    item = {**item, "status": "posted", "url": url}
    if on_posted:
        try:
            on_posted(item, post, url)
        except Exception as e:
            print("after-post hook failed:", e)
    return item


def run_due(blogger, on_posted=None):
    """Post at most one queued product, if one is due."""
    item = _claim()
    return _post(item, blogger, on_posted) if item else None


def post_now(pid: str, blogger, on_posted=None) -> dict:
    """Post one queued product right away (the user asked for it, so no waiting)."""
    item = _claim(pid)
    if not item:
        raise RuntimeError("This product is not in the queue any more.")
    return _post(item, blogger, on_posted)


def pin_after_post(item, post, url):
    """Queue a Pinterest pin for a product that was just published."""
    if item.get("board") and item.get("publish"):
        import pinterest as pn
        p = item["product"]
        rate = round(min(5.0, pw.to_float(str(p.get("evaluate_rate", "")).replace("%", "")) / 20), 1)
        pn.enqueue(item["board"], post["title"], p.get("product_main_image_url", ""), url,
                   pw.to_float(p.get("target_sale_price")), rate, post["labels"])


def remove(pids) -> int:
    """Drop queued products (posted ones stay in the log)."""
    pids = {str(p) for p in pids}

    def op():
        q = load()
        keep = [x for x in q if not (_pid(x) in pids and x["status"] == "queued")]
        save(keep)
        return len(q) - len(keep)
    return sync.transact(op, f"queue: remove {len(pids)}")
