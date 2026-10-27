"""
Post queue for bulk imports: products found with search are posted to Blogger a few
at a time, so the blog doesn't get hundreds of posts in one go (Blogger may flag it as spam).

.env:
  POST_INTERVAL_MIN=20    # minutes between posts
  DAILY_POST_LIMIT=25     # max posts in any 24 hours
"""
import json
import os
import time

import publish as pw

QUEUE_FILE = pw.ROOT / "post_queue.json"
INTERVAL = int(os.getenv("POST_INTERVAL_MIN", "20")) * 60
DAILY_LIMIT = int(os.getenv("DAILY_POST_LIMIT", "25"))


def load() -> list[dict]:
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8")) if QUEUE_FILE.exists() else []


def save(q: list[dict]):
    QUEUE_FILE.write_text(json.dumps(q, indent=1), encoding="utf-8")


def product_key(pid) -> str:
    return f"id:{pid}"


def queued_ids() -> set:
    return {str(x["product"]["product_id"]) for x in load() if x["status"] in ("queued", "posted")}


def add(products: list[dict], publish: bool, board: str = "") -> int:
    q = load()
    have = queued_ids() | {k[3:] for k in pw.load_done() if k.startswith("id:")}
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


def posted_last_day(q) -> int:
    return sum(1 for x in q if x["status"] == "posted" and x.get("done_at", 0) > time.time() - 86400)


def next_time(q) -> float:
    last = max([x.get("done_at", 0) for x in q if x["status"] in ("posted", "failed")], default=0)
    return last + INTERVAL


def run_due(blogger, on_posted=None):
    """Post at most one queued product. Called every minute by the server."""
    q = load()
    item = next((x for x in q if x["status"] == "queued"), None)
    if not item or time.time() < next_time(q) or posted_last_day(q) >= DAILY_LIMIT:
        return
    p = item["product"]
    try:
        problems = pw.quality_check(p)
        if problems:
            raise RuntimeError("Quality filter: " + ", ".join(problems))
        post = pw.build_post(p, item["labels"])
        if item.get("title"):
            post["title"] = item["title"][:140]
        url = pw.blogger_post(blogger, post, item["publish"])
        done = pw.load_done()
        done[product_key(p["product_id"])] = url
        pw.DONE_FILE.write_text(json.dumps(done, indent=1), encoding="utf-8")
        item.update(status="posted", url=url)
        if on_posted:
            on_posted(item, post, url)
    except Exception as e:
        item.update(status="failed", error=str(e)[:200])
    item["done_at"] = time.time()
    save(q)


def remove(pid: str):
    save([x for x in load() if not (str(x["product"]["product_id"]) == pid and x["status"] == "queued")])
