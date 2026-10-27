"""
Penny Wise Finds - AliExpress -> Blogger automation

Usage:
  python publish.py --check            # check config / credentials
  python publish.py --demo             # build a sample post into output/ (no API keys needed)
  python publish.py                    # process links.txt and save posts as DRAFTS
  python publish.py --publish          # process links.txt and PUBLISH posts
  python publish.py --dry-run          # fetch products + build HTML into output/, don't post

links.txt format (one per line, labels optional):
  https://s.click.aliexpress.com/e/_xxxx
  https://s.click.aliexpress.com/e/_yyyy | Home, Deals
"""
import argparse
import hashlib
import hmac
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
LINKS_FILE = ROOT / "links.txt"
load_dotenv(ROOT / ".env")
# Queues and published.json live in STATE_DIR. With CLOUD_SYNC=true it is a git worktree of the
# `state` branch, shared with the GitHub Actions job (see state_sync.py).
CLOUD_SYNC = os.getenv("CLOUD_SYNC", "false").strip().lower() == "true"
STATE_DIR = Path(os.getenv("STATE_DIR") or (ROOT / "state" if CLOUD_SYNC else ROOT))
if not STATE_DIR.is_absolute():
    STATE_DIR = ROOT / STATE_DIR
DONE_FILE = STATE_DIR / "published.json"

ALI_ENDPOINT = "https://api-sg.aliexpress.com/sync"
APP_KEY = os.getenv("ALI_APP_KEY", "").strip()
APP_SECRET = os.getenv("ALI_APP_SECRET", "").strip()
TRACKING_ID = os.getenv("ALI_TRACKING_ID", "").strip() or "default"  # optional: AliExpress uses "default" if not set
BLOG_ID = os.getenv("BLOG_ID", "2976840353661435945").strip()

# Quality filter (edit in .env if you want)
MIN_RATING_PCT = float(os.getenv("MIN_POSITIVE_RATE", "90"))   # AliExpress "evaluate_rate" %
MIN_ORDERS = int(os.getenv("MIN_ORDERS", "10"))
MAX_PRICE = float(os.getenv("MAX_PRICE_USD", "50"))

# Brand / character names that should not appear in titles (trademark safety)
TRADEMARKS = [
    "top gun", "zuko", "avatar", "frankie stein", "monster high", "pj masks", "catboy", "owlette", "gekko",
    "genshin", "pretty derby", "umamusume", "disney", "marvel", "pokemon", "harry potter", "star wars",
    "barbie", "nike", "adidas", "apple", "gucci", "chanel", "wicked", "elphaba", "naruto", "one piece",
]

LABEL_RULES = [
    (r"halloween|pumpkin|skull|ghost|witch|reaper|spooky", ["Halloween"]),
    (r"costume|cosplay|dress|shirt|hoodie|jacket|pants|skirt|coat|sweater|outfit|uniform", ["Fashion"]),
    (r"\brug\b|carpet|lamp|garland|string light|decor|curtain|pillow|cushion|blanket", ["Home"]),
    (r"kitchen|cooking|knife|frying pan|spatula|chopper|peeler", ["Kitchen"]),
    (r"organiz|storage box|basket|shelf|rack", ["Organization"]),
    (r"razor|makeup|beauty|skincare|hair|nail|eyelash", ["Beauty"]),
    (r"earbud|headphone|charger|cable|phone case|smart watch|speaker|power bank", ["Tech"]),
]


# ---------------------------------------------------------------- AliExpress API
def ali_sign(params: dict) -> str:
    base = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hmac.new(APP_SECRET.encode(), base.encode(), hashlib.sha256).hexdigest().upper()


def ali_call(method: str, **biz) -> dict:
    params = {
        "app_key": APP_KEY,
        "method": method,
        "sign_method": "sha256",
        "timestamp": str(int(time.time() * 1000)),
        "format": "json",
        "v": "2.0",
        **{k: str(v) for k, v in biz.items()},
    }
    params["sign"] = ali_sign(params)
    r = requests.post(ALI_ENDPOINT, data=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "error_response" in data:
        raise RuntimeError(f"AliExpress API error: {data['error_response']}")
    return data


SHORT_LINK_RE = re.compile(r"^https?://s\.click\.aliexpress\.com/(e/_|s/)[A-Za-z0-9]{6,}$")
PLACEHOLDER_RE = re.compile(r"_(x+|y+|z+|abc\w*|example\w*)$", re.I)


def resolve_product_id(link: str) -> str:
    m = re.search(r"aliexpress\.[a-z.]+/item/(\d+)\.html", link)
    if m:
        return m.group(1)
    if not SHORT_LINK_RE.match(link) or PLACEHOLDER_RE.search(link):
        raise RuntimeError(f"Not a valid AliExpress product link: {link}")
    # Follow the short affiliate link redirect. Only trust the item id in the
    # redirect URLs themselves - never scrape ids from the landing page, because
    # an invalid link lands on the homepage, which lists random products.
    r = requests.get(link, allow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    for url in [r.url] + [h.headers.get("Location", "") for h in r.history]:
        m = re.search(r"/item/(\d+)\.html", url or "")
        if m:
            return m.group(1)
    raise RuntimeError(f"Link does not point to a product page: {link}")


def get_product(product_id: str) -> dict:
    data = ali_call(
        "aliexpress.affiliate.productdetail.get",
        product_ids=product_id,
        target_currency="USD",
        target_language="EN",
        country="US",
        tracking_id=TRACKING_ID,
    )
    resp = data.get("aliexpress_affiliate_productdetail_get_response", {}).get("resp_result", {})
    if str(resp.get("resp_code")) != "200":
        raise RuntimeError(f"Product {product_id}: {resp.get('resp_msg')}")
    items = resp.get("result", {}).get("products", {}).get("product", [])
    if not items:
        raise RuntimeError(f"Product {product_id} not found (may not be in the affiliate program)")
    return items[0]


SORTS = {"orders": "LAST_VOLUME_DESC", "price_low": "SALE_PRICE_ASC", "price_high": "SALE_PRICE_DESC",
         "discount": "DISCOUNT_DESC"}


def get_categories() -> list[dict]:
    """Top-level AliExpress affiliate categories."""
    data = ali_call("aliexpress.affiliate.category.get")
    resp = data.get("aliexpress_affiliate_category_get_response", {}).get("resp_result", {})
    cats = (resp.get("result") or {}).get("categories", {}).get("category", [])
    top = [{"id": str(c["category_id"]), "name": c["category_name"]} for c in cats
           if not c.get("parent_category_id") and "test" not in c["category_name"].lower()]
    return sorted(top, key=lambda c: c["name"])


def search_products(keywords: str, page: int = 1, sort: str = "orders", min_price: float = 0,
                    max_price: float = 0, page_size: int = 50, category: str = "") -> dict:
    """Find affiliate products by keyword and/or category (aliexpress.affiliate.product.query)."""
    biz = dict(page_no=page, page_size=page_size, sort=SORTS.get(sort, SORTS["orders"]),
               target_currency="USD", target_language="EN", ship_to_country="US", tracking_id=TRACKING_ID)
    if keywords:
        biz["keywords"] = keywords
    if category:
        biz["category_ids"] = category
    if min_price:
        biz["min_sale_price"] = int(min_price * 100)   # cents
    if max_price:
        biz["max_sale_price"] = int(max_price * 100)
    for attempt in range(3):
        try:
            data = ali_call("aliexpress.affiliate.product.query", **biz)
            break
        except RuntimeError as e:
            if "ApiCallLimit" not in str(e) or attempt == 2:
                raise
            time.sleep(1.5)
    resp = data.get("aliexpress_affiliate_product_query_response", {}).get("resp_result", {})
    if str(resp.get("resp_code")) != "200":
        raise RuntimeError(f"Search failed: {resp.get('resp_msg')}")
    res = resp.get("result", {}) or {}
    return {"total": int(res.get("total_record_count") or 0),
            "products": (res.get("products") or {}).get("product", [])}


# ---------------------------------------------------------------- Content
def clean_title(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw).strip()
    for tm in TRADEMARKS:
        t = re.sub(re.escape(tm), "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,-|")
    words = t.split()
    t = " ".join(words[:12])
    return t[:1].upper() + t[1:]


def pick_labels(title: str, extra: list[str], price: float) -> list[str]:
    labels = set(extra or [])
    low = title.lower()
    for pattern, labs in LABEL_RULES:
        if re.search(pattern, low):
            labels.update(labs)
    labels.add("Deals")
    if price and price <= 25:
        labels.add("Under $25")
    return sorted(labels)


def to_float(x) -> float:
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except Exception:
        return 0.0


def quality_check(p: dict) -> list[str]:
    problems = []
    price = to_float(p.get("target_sale_price") or p.get("sale_price"))
    rate = to_float(str(p.get("evaluate_rate", "0")).replace("%", ""))
    orders = int(to_float(p.get("lastest_volume", 0)))
    if price > MAX_PRICE:
        problems.append(f"price ${price:.2f} > ${MAX_PRICE:.0f}")
    if rate and rate < MIN_RATING_PCT:
        problems.append(f"positive rate {rate}% < {MIN_RATING_PCT}%")
    if orders < MIN_ORDERS:
        problems.append(f"only {orders} orders")
    return problems


def build_post(p: dict, extra_labels: list[str]) -> dict:
    raw_title = p.get("product_title", "")
    name = clean_title(raw_title)
    price = to_float(p.get("target_sale_price") or p.get("sale_price"))
    old = to_float(p.get("target_original_price") or p.get("original_price"))
    rate = str(p.get("evaluate_rate", "")).replace("%", "")
    orders = int(to_float(p.get("lastest_volume", 0)))
    img = p.get("product_main_image_url", "")
    link = p.get("promotion_link") or p.get("product_detail_url")
    discount = f" ({p.get('discount')} off)" if p.get("discount") else ""
    labels = pick_labels(raw_title, extra_labels, price)
    n = html.escape(name)

    stars = ""
    if rate:
        # convert positive-feedback % into an approximate 5-star score for the card
        stars_val = round(min(5.0, max(1.0, to_float(rate) / 20)), 1)
        stars = f'<span class="pf-stars">&#9733; {stars_val} ({rate}% positive)</span>'
    attrs = f' data-pid="{p.get("product_id", "")}" data-price="{price:.2f}"' + (f' data-old="{old:.2f}"' if old > price else "")
    if rate:
        attrs += f' data-rating="{round(min(5.0, max(1.0, to_float(rate) / 20)), 1)}"'
    if orders:
        attrs += f' data-reviews="{orders}"'

    body = f"""<p>Looking for a budget-friendly find that&#8217;s actually worth it? Here&#8217;s one that caught our eye on AliExpress: the <b>{n}</b>.</p>

<div class="pf-tip">&#128176; <b>Price check:</b> When we looked, this was on sale for around <b>${price:.2f}</b>{html.escape(discount)}. Prices change by size, color and country &#8212; always check today&#8217;s price.</div>

<div class="pf-product"{attrs}>
  <img src="{html.escape(img)}" alt="{n}"/>
  <div>
    <h3>{n}</h3>
    <div class="pf-meta"><span class="pf-price">~${price:.2f}</span>{stars}<span class="pf-badge">{orders:,}+ sold</span></div>
    <p>A popular pick with {orders:,}+ orders. Check the photos, size options and latest reviews on the product page before you buy.</p>
    <a class="pf-btn" href="{html.escape(link)}" rel="nofollow sponsored noopener" target="_blank">Check Today&#8217;s Price on AliExpress &#8594;</a>
  </div>
</div>

<div class="pf-pros">
  <div class="pro"><b>&#128077; What we like</b><ul><li>Budget-friendly price</li><li>{orders:,}+ orders so far</li>{f"<li>{rate}% positive feedback</li>" if rate else ""}</ul></div>
  <div class="con"><b>&#128078; Keep in mind</b><ul><li>Ships from overseas (about 1&#8211;2 weeks)</li><li>Check the size chart and photos carefully</li></ul></div>
</div>

<p style="text-align:center"><a class="pf-btn" href="{html.escape(link)}" rel="nofollow sponsored noopener" target="_blank">See It on AliExpress &#8594;</a></p>

<p><small><i>This post contains affiliate links. If you buy through them, we may earn a small commission at no extra cost to you. Prices, ratings and availability were accurate at the time of writing and may change.</i></small></p>"""

    title = f"{name}: A Budget Find Around ${price:.0f}" if price >= 1 else name
    return {"title": title[:140], "labels": labels, "content": body, "link": link, "price": price}


# ---------------------------------------------------------------- Blogger API
def blogger_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/blogger"]
    token = ROOT / "token.json"
    creds = Credentials.from_authorized_user_file(str(token), scopes) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.getenv("CI"):
                raise RuntimeError("Google login expired. Run the dashboard on the laptop once, then update "
                                   "the BLOGGER_TOKEN_JSON secret (see SETUP-GUIDE.md, Cloud).")
            secret = ROOT / "client_secret.json"
            if not secret.exists():
                sys.exit("client_secret.json not found. See SETUP-GUIDE.md step 2.")
            creds = InstalledAppFlow.from_client_secrets_file(str(secret), scopes).run_local_server(port=0)
        if not os.getenv("CI"):
            token.write_text(creds.to_json())
    return build("blogger", "v3", credentials=creds)


def blogger_post(svc, post: dict, publish: bool) -> str:
    body = {"title": post["title"], "content": post["content"], "labels": post["labels"]}
    res = svc.posts().insert(blogId=BLOG_ID, body=body, isDraft=not publish).execute()
    return res.get("url") or f"draft id {res.get('id')}"


# ---------------------------------------------------------------- Helpers
def read_links() -> list[tuple[str, list[str]]]:
    if not LINKS_FILE.exists():
        LINKS_FILE.write_text("# Paste AliExpress links here, one per line.\n# Optional labels: link | Home, Deals\n", encoding="utf-8")
    out = []
    for line in LINKS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        link, _, labs = line.partition("|")
        out.append((link.strip(), [x.strip() for x in labs.split(",") if x.strip()]))
    return out


def load_done() -> dict:
    return json.loads(DONE_FILE.read_text(encoding="utf-8")) if DONE_FILE.exists() else {}


def save_html(post: dict, name: str):
    OUT.mkdir(exist_ok=True)
    f = OUT / f"{name}.html"
    f.write_text(f"<!-- {post['title']} | labels: {', '.join(post['labels'])} -->\n{post['content']}", encoding="utf-8")
    return f


def check():
    ok = True
    for k, v in [("ALI_APP_KEY", APP_KEY), ("ALI_APP_SECRET", APP_SECRET)]:
        print(f"  {k:16} {'OK' if v else 'MISSING (add to .env)'}")
        ok &= bool(v)
    print(f"  {'ALI_TRACKING_ID':16} {TRACKING_ID} (optional)")
    print(f"  {'BLOG_ID':16} {BLOG_ID}")
    sec = (ROOT / "client_secret.json").exists()
    print(f"  {'client_secret':16} {'OK' if sec else 'MISSING (Google Cloud OAuth JSON)'}")
    print(f"  {'token.json':16} {'OK (signed in)' if (ROOT / 'token.json').exists() else 'not yet (created on first run)'}")
    print(f"  {'links.txt':16} {len(read_links())} link(s)")
    return ok and sec


def demo():
    sample = {
        "product_title": "Halloween LED String Lights Pumpkin Ghost Spider Web Hanging Lamp",
        "target_sale_price": "1.40", "target_original_price": "4.05", "discount": "65%",
        "evaluate_rate": "96.0%", "lastest_volume": "3000",
        "product_main_image_url": "https://ae-pic-a1.aliexpress-media.com/kf/Sc59f0c881d6d423b846d80ab4c71d4aee.jpg",
        "promotion_link": "https://s.click.aliexpress.com/e/_c2R7m1N5",
    }
    post = build_post(sample, [])
    f = save_html(post, "demo-post")
    print("Title :", post["title"])
    print("Labels:", ", ".join(post["labels"]))
    print("Saved :", f)
    print("Quality check:", quality_check(sample) or "passed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--publish", action="store_true", help="publish instead of saving drafts")
    ap.add_argument("--force", action="store_true", help="skip the quality filter")
    a = ap.parse_args()

    if a.demo:
        return demo()
    print("Config:")
    ready = check()
    if a.check:
        return
    if not (APP_KEY and APP_SECRET):
        sys.exit("\nAliExpress API keys are missing. Fill in .env first (see SETUP-GUIDE.md).")

    links = read_links()
    if not links:
        sys.exit("\nlinks.txt is empty. Paste AliExpress links into it.")
    done = load_done()
    svc = None if a.dry_run else blogger_service()

    for i, (link, labs) in enumerate(links, 1):
        print(f"\n[{i}/{len(links)}] {link}")
        if link in done:
            print("  skip: already posted ->", done[link])
            continue
        try:
            pid = resolve_product_id(link)
            p = get_product(pid)
            problems = quality_check(p)
            if problems and not a.force:
                print("  SKIPPED (quality):", "; ".join(problems))
                continue
            post = build_post(p, labs)
            post["link"] = link  # keep your own affiliate link
            post["content"] = post["content"].replace(html.escape(p.get("promotion_link") or ""), html.escape(link)) if p.get("promotion_link") else post["content"]
            f = save_html(post, pid)
            print("  title :", post["title"])
            print("  labels:", ", ".join(post["labels"]))
            print("  html  :", f.name)
            if a.dry_run:
                continue
            url = blogger_post(svc, post, a.publish)
            print("  " + ("PUBLISHED" if a.publish else "DRAFT SAVED") + ":", url)
            done[link] = url
            DONE_FILE.write_text(json.dumps(done, indent=1), encoding="utf-8")
            time.sleep(2)
        except Exception as e:
            print("  ERROR:", e)


if __name__ == "__main__":
    main()
