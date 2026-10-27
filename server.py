"""
Penny Wise Finds dashboard backend.

  python server.py      -> open http://127.0.0.1:5050

Serves the React UI (ui/dist) and a small JSON API that reuses publish.py.
Runs on 127.0.0.1 only, so API keys never leave this computer.
"""
import json
import re
import threading
import time

from flask import Flask, jsonify, redirect, request, send_from_directory

import auto_update as au
import pinterest as pn
import post_queue as pq
import publish as pw
import update_prices as up

DIST = pw.ROOT / "ui" / "dist"
app = Flask(__name__, static_folder=None)
lock = threading.Lock()
_svc = None


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
    return jsonify({
        "aliKey": bool(pw.APP_KEY),
        "aliSecret": bool(pw.APP_SECRET),
        "trackingId": pw.TRACKING_ID,
        "blogId": pw.BLOG_ID,
        "clientSecret": (pw.ROOT / "client_secret.json").exists(),
        "signedIn": (pw.ROOT / "token.json").exists(),
        "filters": {"minPositive": pw.MIN_RATING_PCT, "minOrders": pw.MIN_ORDERS, "maxPrice": pw.MAX_PRICE},
        "published": len(pw.load_done()),
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
            if link in done:
                out.append({"link": link, "ok": False, "message": "Already posted"})
                continue
            try:
                url = pw.blogger_post(blogger(), {
                    "title": it["title"][:140],
                    "labels": it.get("labels", []),
                    "content": it["content"],
                }, publish)
                done[link] = url
                pw.DONE_FILE.write_text(json.dumps(done, indent=1), encoding="utf-8")
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
    b = request.get_json(force=True)
    kw = (b.get("keywords") or "").strip()
    if not kw:
        return jsonify({"error": "Type a keyword.", "items": []})
    try:
        r = pw.search_products(kw, int(b.get("page") or 1), b.get("sort") or "orders",
                               pw.to_float(b.get("minPrice")), pw.to_float(b.get("maxPrice")))
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
    q = pq.load()
    items = [{
        "productId": str(x["product"]["product_id"]), "title": x.get("title") or x["product"].get("product_title", ""),
        "image": x["product"].get("product_main_image_url", ""), "status": x["status"], "publish": x["publish"],
        "url": x.get("url", ""), "error": x.get("error", ""), "doneAt": x.get("done_at", 0),
    } for x in reversed(q)][:200]
    return jsonify({
        "items": items, "queued": sum(1 for x in q if x["status"] == "queued"),
        "postedToday": pq.posted_last_day(q), "dailyLimit": pq.DAILY_LIMIT,
        "intervalMin": pq.INTERVAL // 60, "next": max(pq.next_time(q), time.time()),
    })


@app.post("/api/post-queue/remove")
def post_queue_remove():
    pq.remove(str(request.get_json(force=True).get("productId", "")))
    return jsonify({"ok": True})


def _pin_after_post(item, post, url):
    if item.get("board") and item.get("publish"):
        p = item["product"]
        rate = round(min(5.0, pw.to_float(str(p.get("evaluate_rate", "")).replace("%", "")) / 20), 1)
        pn.enqueue(item["board"], post["title"], p.get("product_main_image_url", ""), url,
                   pw.to_float(p.get("target_sale_price")), rate, post["labels"])


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
    return redirect("http://127.0.0.1:5050/?pinterest=ok")


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
    return jsonify({"items": list(reversed(pn.load_queue()))[:100], "intervalMin": pn.INTERVAL // 60})


def pin_worker():
    while True:
        try:
            with lock:
                pq.run_due(blogger(), _pin_after_post)
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


# ---------------------------------------------------------------- static UI
@app.get("/")
@app.get("/<path:path>")
def ui(path="index.html"):
    if not DIST.exists():
        return "UI not built yet. Run: cd ui && npm install && npm run build", 503
    target = DIST / path
    return send_from_directory(DIST, path if target.is_file() else "index.html")


if __name__ == "__main__":
    print("Penny Wise Finds dashboard -> http://127.0.0.1:5050")
    threading.Thread(target=pin_worker, daemon=True).start()
    threading.Thread(target=price_worker, daemon=True).start()
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
