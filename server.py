"""
Penny Wise Finds dashboard backend.

  python server.py      -> open http://127.0.0.1:5050

Serves the React UI (ui/dist) and a small JSON API that reuses publish.py.
Runs on 127.0.0.1 only, so API keys never leave this computer.
"""
import json
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

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
                out.append({"link": link, "ok": True, "url": url})
                time.sleep(1.5)
            except Exception as e:
                out.append({"link": link, "ok": False, "message": str(e)[:200]})
    return jsonify({"results": out})


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
        links = {l for p in posts_ for l in up.LINK_RE.findall(p.get("content", ""))}
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
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
