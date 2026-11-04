"""
Penny Wise Finds dashboard backend.

  python server.py      -> open http://127.0.0.1:5050

Serves the React UI (ui/dist) and a small JSON API that reuses publish.py.
On the laptop it runs on 127.0.0.1 only, so API keys never leave this computer.

Hosted (Render etc., see SETUP-GUIDE.md "Online"): set PORT and APP_PASSWORD. Then it listens on
0.0.0.0, every /api call needs a login, and the state branch is cloned with GITHUB_TOKEN.
"""
import hmac
import json
import os
import re
import subprocess
import threading
import time
from datetime import timedelta

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session
from werkzeug.middleware.proxy_fix import ProxyFix

import auto_update as au
import pinterest as pn
import post_queue as pq
import publish as pw
import state_sync as sync
import update_prices as up

DIST = pw.ROOT / "ui" / "dist"
HOSTED = bool(os.getenv("PORT"))
PASSWORD = os.getenv("APP_PASSWORD", "")
app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config.update(SECRET_KEY=os.getenv("SECRET_KEY") or os.urandom(32).hex(),
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30), SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=HOSTED)
lock = threading.Lock()
_svc = None


# ---------------------------------------------------------------- login (only when APP_PASSWORD is set)
_fails = {}   # ip -> [count, first failure time]
OPEN = {"/api/login", "/api/session"}


@app.before_request
def need_login():
    if PASSWORD and request.path.startswith("/api/") and request.path not in OPEN and not session.get("ok"):
        return jsonify({"error": "login"}), 401


@app.errorhandler(Exception)
def api_error(e):
    """Show a readable message in the dashboard instead of an HTML error page."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    print("error:", request.path, e)
    return jsonify({"error": str(e)[:300] or e.__class__.__name__}), 500


@app.get("/api/session")
def session_info():
    return jsonify({"needLogin": bool(PASSWORD), "loggedIn": bool(session.get("ok")) or not PASSWORD})


@app.post("/api/login")
def login():
    ip = request.remote_addr or "?"
    n, since = _fails.get(ip, [0, time.time()])
    if n >= 5 and time.time() - since < 600:
        return jsonify({"ok": False, "message": "Too many wrong passwords. Try again in 10 minutes."}), 429
    pwd = str((request.get_json(force=True, silent=True) or {}).get("password", ""))
    if PASSWORD and hmac.compare_digest(pwd.encode(), PASSWORD.encode()):
        _fails.pop(ip, None)
        session.permanent = True
        session["ok"] = True
        return jsonify({"ok": True})
    _fails[ip] = [n + 1 if time.time() - since < 600 else 1, since if time.time() - since < 600 else time.time()]
    time.sleep(1)
    return jsonify({"ok": False, "message": "Wrong password."}), 401


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


def blogger():
    global _svc
    if _svc is None:
        _svc = pw.blogger_service()
    return _svc


def parse_links(text: str):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        link, _, labs = line.partition("|")
        out.append((link.strip(), [x.strip() for x in labs.split(",") if x.strip()]))
    return out


@app.get("/api/status")
def status():
    sync.refresh()
    return jsonify({
        "aliKey": bool(pw.APP_KEY),
        "aliSecret": bool(pw.APP_SECRET),
        "trackingId": pw.TRACKING_ID,
        "blogId": pw.BLOG_ID,
        "clientSecret": (pw.ROOT / "client_secret.json").exists(),
        "signedIn": (pw.ROOT / "token.json").exists(),
        "hosted": HOSTED,
        "pinEvery": pn.INTERVAL // 60,
        "filters": {"minPositive": pw.MIN_RATING_PCT, "minOrders": pw.MIN_ORDERS, "maxPrice": pw.MAX_PRICE},
        "published": len(pw.load_done()),
        "cloud": pw.CLOUD_SYNC,
        "pinterest": {"configured": pn.configured(), "connected": pn.connected(),
                      "sandbox": "sandbox" in pn.API},
    })


@app.get("/api/links-file")
def links_file():
    return jsonify({"text": pw.LINKS_FILE.read_text(encoding="utf-8") if pw.LINKS_FILE.exists() else ""})


@app.post("/api/preview")
def preview():
    body = request.get_json(force=True)
    done = pw.load_done()
    results = []
    for link, labels in parse_links(body.get("text", "")):
        item = {"link": link}
        if link in done:
            item.update(status="duplicate", message=f"Already posted: {done[link]}")
            results.append(item)
            continue
        try:
            pid = pw.resolve_product_id(link)
            if f"id:{pid}" in done:
                item.update(status="duplicate", message=f"Already posted: {done[f'id:{pid}']}")
                results.append(item)
                continue
            p = pw.get_product(pid)
            post = pw.build_post(p, labels)
            # keep the user's own affiliate link in the post
            promo = p.get("promotion_link")
            if promo:
                post["content"] = post["content"].replace(pw.html.escape(promo), pw.html.escape(link))
            problems = pw.quality_check(p)
            item.update(
                status="warning" if problems else "ok",
                problems=problems,
                productId=pid,
                rawTitle=p.get("product_title", ""),
                image=p.get("product_main_image_url", ""),
                price=pw.to_float(p.get("target_sale_price")),
                oldPrice=pw.to_float(p.get("target_original_price")),
                positive=p.get("evaluate_rate", ""),
                orders=int(pw.to_float(p.get("lastest_volume", 0))),
                title=post["title"],
                labels=post["labels"],
                content=post["content"],
            )
        except Exception as e:
            msg = str(e)
            item.update(status="error", message=msg[:200])
        results.append(item)
        time.sleep(0.6)
    return jsonify({"items": results})


@app.post("/api/post")
def make_post():
    body = request.get_json(force=True)
    publish = bool(body.get("publish"))
    board = (body.get("board") or "").strip() if publish else ""
    out = []
    with lock:
        done = pw.load_done()
        for it in body.get("items", []):
            link = it["link"]
            key = f"id:{it['productId']}" if it.get("productId") else ""
            if link in done or key in done:
                out.append({"link": link, "ok": False, "message": "Already posted"})
                continue
            try:
                url = pw.blogger_post(blogger(), {
                    "title": it["title"][:140],
                    "labels": it.get("labels", []),
                    "content": it["content"],
                }, publish)
                done[link] = url
                if key:
                    done[key] = url

                def record(link=link, key=key, url=url):
                    d = pw.load_done()
                    d[link] = url
                    if key:   # id key: search / queue see it too
                        d[key] = url
                    pw.DONE_FILE.write_text(json.dumps(d, indent=1), encoding="utf-8")
                sync.transact(record, "published: link")
                res = {"link": link, "ok": True, "url": url}
                if board:
                    rating = round(min(5.0, pw.to_float(str(it.get("positive", "")).replace("%", "")) / 20), 1)
                    res["pinAt"] = pn.enqueue(board, it["title"], it.get("image", ""), url,
                                              it.get("price") or 0, rating, it.get("labels"))
                out.append(res)
                time.sleep(1.5)
            except Exception as e:
                out.append({"link": link, "ok": False, "message": str(e)[:200]})
    return jsonify({"results": out})


# ---------------------------------------------------------------- Find products (bulk import)
@app.post("/api/search")
def search():
    sync.refresh()
    b = request.get_json(force=True)
    kw = (b.get("keywords") or "").strip()
    cat = str(b.get("category") or "").strip()
    if not kw and not cat:
        return jsonify({"error": "Type a keyword or pick a category.", "items": []})
    try:
        r = pw.search_products(kw, int(b.get("page") or 1), b.get("sort") or "orders",
                               pw.to_float(b.get("minPrice")), pw.to_float(b.get("maxPrice")), category=cat)
    except Exception as e:
        return jsonify({"error": str(e)[:200], "items": []})
    done = {k[3:] for k in pw.load_done() if k.startswith("id:")}
    queued = pq.queued_ids()
    min_orders = int(pw.to_float(b.get("minOrders")))
    min_rate = pw.to_float(b.get("minRating"))
    items = []
    for p in r["products"]:
        pid = str(p["product_id"])
        price = pw.to_float(p.get("target_sale_price"))
        rate = pw.to_float(str(p.get("evaluate_rate", "")).replace("%", ""))
        orders = int(pw.to_float(p.get("lastest_volume", 0)))
        if orders < min_orders or (min_rate and rate < min_rate):
            continue
        items.append({
            "productId": pid, "product": p,
            "title": pw.clean_title(p.get("product_title", "")),
            "labels": pw.pick_labels(p.get("product_title", ""), [], price),
            "image": p.get("product_main_image_url", ""), "price": price,
            "oldPrice": pw.to_float(p.get("target_original_price")), "positive": p.get("evaluate_rate", ""),
            "orders": orders, "commission": p.get("commission_rate", ""),
            "category": p.get("second_level_category_name") or p.get("first_level_category_name", ""),
            "problems": pw.quality_check(p),
            "state": "posted" if pid in done else "queued" if pid in queued else "",
        })
    return jsonify({"total": r["total"], "found": len(r["products"]), "items": items})


_cats = []


@app.get("/api/categories")
def categories():
    global _cats
    if not _cats:
        try:
            _cats = pw.get_categories()
        except Exception as e:
            return jsonify({"items": [], "error": str(e)[:200]})
    return jsonify({"items": _cats})


@app.post("/api/import")
def import_products():
    b = request.get_json(force=True)
    products = []
    for it in b.get("items", []):
        p = dict(it["product"])
        p["_title"], p["_labels"] = it.get("title", ""), it.get("labels", [])
        products.append(p)
    added = pq.add(products, bool(b.get("publish")), (b.get("board") or "").strip())
    return jsonify({"added": added, "skipped": len(products) - added})


@app.get("/api/post-queue")
def post_queue():
    sync.refresh()
    q = pq.load()
    items = [{
        "productId": str(x["product"]["product_id"]), "title": x.get("title") or x["product"].get("product_title", ""),
        "image": x["product"].get("product_main_image_url", ""), "status": x["status"], "publish": x["publish"],
        "url": x.get("url", ""), "error": x.get("error", ""), "doneAt": x.get("done_at", 0),
        "aliUrl": x["product"].get("promotion_link") or x["product"].get("product_detail_url", ""),
        "price": pw.to_float(x["product"].get("target_sale_price")),
    } for x in reversed(q)][:200]
    return jsonify({
        "items": items, "queued": sum(1 for x in q if x["status"] == "queued"),
        "postedToday": pq.posted_last_day(q), "dailyLimit": pq.DAILY_LIMIT,
        "intervalMin": pq.INTERVAL // 60, "next": max(pq.next_time(q), time.time()),
    })


@app.post("/api/post-queue/post-now")
def post_queue_now():
    pid = str(request.get_json(force=True).get("productId", ""))
    try:
        with lock:
            item = pq.post_now(pid, blogger(), pq.pin_after_post)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)[:200]})
    if item["status"] != "posted":
        return jsonify({"ok": False, "message": item.get("error", "Failed")})
    return jsonify({"ok": True, "url": item["url"], "publish": item["publish"]})


@app.post("/api/post-queue/remove")
def post_queue_remove():
    b = request.get_json(force=True)
    ids = b.get("productIds") or [b.get("productId", "")]
    return jsonify({"ok": True, "removed": pq.remove(ids)})


@app.post("/api/post-queue/retry")
def post_queue_retry():
    b = request.get_json(force=True)
    return jsonify({"ok": True, "retried": pq.retry(b.get("productIds") or [b.get("productId", "")])})


@app.get("/api/history")
def history():
    done = pw.load_done()
    return jsonify({"items": [{"link": k, "url": v} for k, v in reversed(list(done.items()))]})


@app.get("/api/posts")
def posts():
    r = blogger().posts().list(blogId=pw.BLOG_ID, maxResults=50, fetchBodies=False,
                               status=["LIVE", "DRAFT"], fetchImages=True).execute()
    items = [{
        "id": p["id"], "title": p["title"], "status": p.get("status"), "url": p.get("url"),
        "labels": p.get("labels", []), "published": p.get("published"),
        "image": (p.get("images") or [{}])[0].get("url", ""),
    } for p in r.get("items", [])]
    return jsonify({"items": items})


def _all_posts():
    out, token = [], None
    while True:
        r = blogger().posts().list(blogId=pw.BLOG_ID, maxResults=50, fetchBodies=True, pageToken=token,
                                   status=["LIVE", "DRAFT"]).execute()
        out += r.get("items", [])
        token = r.get("nextPageToken")
        if not token:
            return out


@app.post("/api/prices")
def prices():
    apply = bool(request.get_json(force=True).get("apply"))
    with lock:
        posts_ = _all_posts()
        links = up.collect_keys(posts_)
        price_map = up.fetch_prices(links)
        rows = []
        for p in posts_:
            new_html, changes = up.update_content(p["content"], price_map)
            new_title = up.TITLE_FIXES.get(p["title"], p["title"])
            if new_html == p["content"] and new_title == p["title"]:
                continue
            rows.append({"title": p["title"], "newTitle": new_title if new_title != p["title"] else "", "changes": changes})
            if apply:
                b = {"content": new_html}
                if new_title != p["title"]:
                    b["title"] = new_title
                blogger().posts().patch(blogId=pw.BLOG_ID, postId=p["id"], body=b).execute()
                time.sleep(1)
    found = sum(1 for v in price_map.values() if "price" in v)
    return jsonify({"applied": apply, "links": len(price_map), "found": found, "rows": rows})


# ---------------------------------------------------------------- Pinterest
@app.get("/api/pinterest/login")
def pinterest_login():
    if not pn.configured():
        return "Add PINTEREST_APP_ID and PINTEREST_APP_SECRET to .env, then restart.", 400
    return redirect(pn.auth_url())


@app.get("/api/pinterest/callback")
def pinterest_callback():
    try:
        pn.finish_login(request.args.get("code", ""), request.args.get("state", ""))
    except Exception as e:
        return f"Pinterest login failed: {e}", 400
    return redirect("/?pinterest=ok")


@app.post("/api/pinterest/pin-post")
def pin_post():
    body = request.get_json(force=True)
    board = (body.get("board") or "").strip()
    if not board:
        return jsonify({"ok": False, "message": "Pick a board first."})
    p = blogger().posts().get(blogId=pw.BLOG_ID, postId=body["postId"]).execute()
    if p.get("status") != "LIVE" or not p.get("url"):
        return jsonify({"ok": False, "message": "Only live posts can be pinned."})
    html_ = p.get("content", "")
    img = re.search(r'class="pf-product"[^>]*>\s*<img src="([^"]+)"', html_) or re.search(r'<img[^>]+src="([^"]+)"', html_)
    price = re.search(r'data-price="([\d.]+)"', html_)
    rating = re.search(r'data-rating="([\d.]+)"', html_)
    if not img:
        return jsonify({"ok": False, "message": "No image found in this post."})
    due = pn.enqueue(board, p["title"], pw.html.unescape(img.group(1)), p["url"],
                     float(price.group(1)) if price else 0, float(rating.group(1)) if rating else 0,
                     p.get("labels", []))
    return jsonify({"ok": True, "pinAt": due})


@app.get("/api/pinterest/queue")
def pinterest_queue():
    sync.refresh()
    return jsonify({"items": list(reversed(pn.load_queue()))[:100], "intervalMin": pn.INTERVAL // 60})


def pin_worker():
    while True:
        try:
            with lock:
                pq.run_due(blogger(), pq.pin_after_post)
        except Exception as e:
            print("post worker:", e)
        try:
            pn.run_due()
        except Exception as e:
            print("pin worker:", e)
        time.sleep(60)


@app.get("/api/pinterest/boards")
def pinterest_boards():
    try:
        return jsonify({"items": pn.boards()})
    except Exception as e:
        return jsonify({"error": str(e)[:200], "items": []})


# ---------------------------------------------------------------- daily auto price update
_auto = {"running": False}


def _run_auto():
    if _auto["running"]:
        return
    _auto["running"] = True
    try:
        au.run(blogger())
    except Exception as e:
        print("auto price update:", e)
    finally:
        _auto["running"] = False


def price_worker():
    time.sleep(120)   # let the dashboard start first
    while True:
        if au.due():
            _run_auto()
        time.sleep(600)


@app.get("/api/auto-update")
def auto_status():
    sync.refresh()
    st = au.load_state()
    items = [{"postId": k, **v} for k, v in st.get("unavailable", {}).items()]
    return jsonify({
        "enabled": au.ENABLED, "autoDraft": au.AUTO_DRAFT, "days": au.UNAVAILABLE_DAYS,
        "running": _auto["running"], "lastRun": st.get("last_run", 0),
        "next": st.get("last_run", 0) + au.EVERY, "last": st.get("last"), "unavailable": items,
    })


@app.post("/api/auto-update/run")
def auto_run_now():
    if not _auto["running"]:
        threading.Thread(target=_run_auto, daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/unavailable/draft")
def unavailable_draft():
    pid = str(request.get_json(force=True).get("postId", ""))
    try:
        blogger().posts().revert(blogId=pw.BLOG_ID, postId=pid).execute()
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)[:200]})
    au.mark_drafted(pid)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- image proxy
# AliExpress's image CDN answers 403/429 when a browser asks for 50 images at once.
# The dashboard loads product images through here: a few at a time, with retries and a disk cache.
IMG_CACHE = pw.ROOT / "output" / "imgcache"
IMG_HOSTS = re.compile(r"^https://[a-z0-9.-]+\.(aliexpress-media\.com|alicdn\.com)/")
_img_slots = threading.Semaphore(4)


@app.get("/api/img")
def img_proxy():
    import hashlib
    import requests
    url = request.args.get("u", "")
    if not IMG_HOSTS.match(url):
        return "bad image url", 400
    IMG_CACHE.mkdir(parents=True, exist_ok=True)
    path = IMG_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img")
    if not path.exists():
        data = None
        with _img_slots:
            for attempt in range(5):
                for u in (url + "_350x350.jpg", url):   # small thumbnail first
                    try:
                        r = requests.get(u, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                    except requests.RequestException:
                        continue
                    if r.ok and r.headers.get("content-type", "").startswith("image/"):
                        data = r.content
                        break
                if data:
                    break
                time.sleep(1.5 * (attempt + 1))
        if not data:
            return "image unavailable", 502
        path.write_bytes(data)
    body = path.read_bytes()
    ctype = "image/webp" if body[8:12] == b"WEBP" else "image/png" if body[1:4] == b"PNG" else "image/jpeg"
    return Response(body, mimetype=ctype, headers={"Cache-Control": "public, max-age=604800"})


# ---------------------------------------------------------------- static UI
@app.get("/")
@app.get("/<path:path>")
def ui(path="index.html"):
    if not DIST.exists():
        return "UI not built yet. Run: cd ui && npm install && npm run build", 503
    target = DIST / path
    resp = send_from_directory(DIST, path if target.is_file() else "index.html")
    if not target.is_file() or path == "index.html":
        resp.headers["Cache-Control"] = "no-cache"   # always pick up a fresh build after an update
    return resp


def port_free(port=5050) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):   # Windows: fail if anything holds the port
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def hosted_setup():
    """Online host: secrets come from env vars, the state branch is cloned (the disk is temporary)."""
    if not PASSWORD:
        raise SystemExit("Set APP_PASSWORD: the dashboard is on the internet and needs a password.")
    if not pw.CLOUD_SYNC:
        raise SystemExit("Set CLOUD_SYNC=true: the host's disk is temporary, so the queues live in the state branch.")
    token = os.getenv("BLOGGER_TOKEN_JSON", "").strip()
    if token and not (pw.ROOT / "token.json").exists():
        (pw.ROOT / "token.json").write_text(token, encoding="utf-8")
    if not (pw.STATE_DIR / ".git").exists():
        repo = os.getenv("GITHUB_REPO") or os.getenv("RENDER_GIT_REPO_SLUG", "")
        gh = os.getenv("GITHUB_TOKEN", "").strip()
        if not (repo and gh):
            raise SystemExit("Set GITHUB_TOKEN (and GITHUB_REPO=owner/name) so the dashboard can read the queues.")
        url = f"https://x-access-token:{gh}@github.com/{repo}.git"
        r = subprocess.run(["git", "clone", "-q", "--branch", "state", "--single-branch", url, str(pw.STATE_DIR)],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("Could not clone the state branch: " + r.stderr.replace(gh, "***")[:300])
        for k, v in (("user.name", "pennywise-dashboard"), ("user.email", "dashboard@users.noreply.github.com")):
            subprocess.run(["git", "-C", str(pw.STATE_DIR), "config", k, v], check=True)


if __name__ == "__main__":
    if HOSTED:
        hosted_setup()
    # Only one dashboard may run: two copies would both run the post/pin queues and post twice.
    elif not port_free():
        print("The dashboard is already running -> http://127.0.0.1:5050")
        raise SystemExit(1)
    else:
        print("Penny Wise Finds dashboard -> http://127.0.0.1:5050")
    if pw.CLOUD_SYNC:
        # GitHub Actions (cloud_run.py) posts, pins and updates prices; the laptop only edits the queue.
        if not (pw.STATE_DIR / ".git").exists():
            raise SystemExit("CLOUD_SYNC is on but the state folder is missing. Run: python setup_cloud.py")
        sync.pull()
        print("Cloud mode: posting, pins and price updates run on GitHub Actions.")
    else:
        threading.Thread(target=pin_worker, daemon=True).start()
        threading.Thread(target=price_worker, daemon=True).start()
    from waitress import serve
    serve(app, host="0.0.0.0" if HOSTED else "127.0.0.1", port=int(os.getenv("PORT") or 5050), threads=8)
