"""
Refresh product prices in existing Penny Wise Finds posts using the AliExpress API (USD, US).

  python update_prices.py            # dry run: show what would change
  python update_prices.py --apply    # update posts on Blogger
"""
import argparse
import json
import re
import sys
import time

import publish as pw

LINK_RE = re.compile(r'https://s\.click\.aliexpress\.com/(?:e/_|s/)[A-Za-z0-9]+')
PID_RE = re.compile(r'data-pid="(\d+)"')
BOX_RE = re.compile(r'<div class="pf-product"[^>]*>.*?</a>\s*</div>\s*</div>', re.S)


def fmt(p: float) -> str:
    return f"{p:.2f}".rstrip("0").rstrip(".") if p < 10 else f"{p:.0f}" if p >= 20 else f"{p:.2f}"


def box_keys(box: str) -> list[str]:
    """Price lookup keys for a product box: its product id (newer posts) and its links."""
    m = PID_RE.search(box)
    return ([f"pid:{m.group(1)}"] if m else []) + LINK_RE.findall(box)


def collect_keys(posts) -> set:
    keys = set()
    for p in posts:
        for m in BOX_RE.finditer(p.get("content", "")):
            k = box_keys(m.group(0))
            if k:
                keys.add(k[0])
    return keys


def fetch_prices(links):
    cache = {}
    for link in sorted(links):
        for attempt in range(4):
            try:
                pid = link[4:] if link.startswith("pid:") else pw.resolve_product_id(link)
                p = pw.get_product(pid)
                sale = pw.to_float(p.get("target_sale_price"))
                orig = pw.to_float(p.get("target_original_price"))
                cache[link] = {"pid": pid, "price": sale, "old": orig if orig > sale else 0}
                print(f"  {link[-10:]}  ${sale:>7.2f}  {p.get('product_title','')[:55]}")
                break
            except Exception as e:
                msg = str(e)
                if "ApiCallLimit" in msg and attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                cache[link] = {"error": msg[:120], "notfound": "not found" in msg}
                print(f"  {link[-10:]}  {'NOT FOUND' if 'not found' in msg else 'ERROR ' + msg[:90]}")
                break
        time.sleep(1.0)
    return cache


# Titles that mention old (wrong) prices -> corrected titles
TITLE_FIXES = {
    "Funny “Old Lady” Balaclava: A $1.40 Costume Laugh": "Funny “Old Lady” Balaclava: A Cheap Costume Laugh",
    "$1.40 Grim Reaper Costume Set (Robe + Sickle)": "Budget Grim Reaper Costume Set (Robe + Sickle)",
    "Ice Silk Sun Mask: Cool Full-Face UV Cover for $1.40": "Ice Silk Sun Mask: Cool Full-Face UV Cover for Under $4",
    "Kids Winter Balaclava: Warm Face Cover for Under $2": "Kids Winter Balaclava: Warm Face Cover for Under $4",
    "Knit Winter Balaclava Ski Mask for About $2": "Knit Winter Balaclava Ski Mask for About $4",
    "Fall Leaf LED Garland: Cozy Autumn Glow for About $1.40": "Fall Leaf LED Garland: Cozy Autumn Glow on a Budget",
    "Cute Halloween LED String Lights for Under $2 (3,000+ Sold!)": "Cute Halloween LED String Lights for Under $4 (2,700+ Sold!)",
    "7 Halloween Costume Finds for Kids & Adults (From $1.40)": "7 Halloween Costume Finds for Kids & Adults (Budget Picks)",
    "8 Budget Face Masks & Balaclavas for Every Season (Most Under $3)": "8 Budget Face Masks & Balaclavas for Every Season (Most Under $5)",
    "Color-Changing Thermal Balaclava: A Warm Winter Find Around $11": "Color-Changing Thermal Balaclava: A Warm Winter Find Around $16",
    "5 Halloween & Fall Decor Finds Under $20 (Most Under $2!)": "5 Halloween & Fall Decor Finds Under $15",
    "6-Blade Razor Set Deal: A Budget Shaving Find for About $1": "6-Blade Razor Set Deal: A Budget Shaving Find for Under $3",
}

# Body text that mentions old prices
TEXT_FIXES = [
    (re.compile(r'&#9888;&#65039; <b>Price warning:</b>.*?before you buy\.', re.S),
     'Price update: we checked again and this listing now shows around <b>$5.75</b> in the US. It has no ratings yet, though the store has 97% positive feedback.'),
    (re.compile(r'<li>Price looked very high</li>'), '<li>Brand-new listing</li>'),
    (re.compile(r'around <b>&#8364;1\.00</b> \(about \$1\)'), 'around <b>$2.65</b>'),
    (re.compile(r'<b>Deal price: ~&#8364;1\.00</b>|Deal price: ~&#8364;1\.00'), '~$2.65'),
    (re.compile(r'most for under \$3\.'), 'most for under $5.'),
    (re.compile(r'around <b>\$30&#8211;35</b>'), 'around <b>$32</b>'),
    (re.compile(r'For only around a dollar|At around a dollar'), 'At under $3'),
    (re.compile(r'(the clear favorite with over) 2,000 sold'), r'\1 2,000 sold'),
]


def update_box(box: str, info: dict) -> str:
    if info.get("notfound"):
        # price can't be verified in the US -> don't show an old (too low) price
        box = re.sub(r'\s*data-(price|old)="[^"]*"', '', box)
        box = re.sub(r'<span class="pf-price">[^<]*</span>', '<span class="pf-price">Check price</span>', box, count=1)
        return box
    price = fmt(info["price"])
    if 'data-price="' in box:
        box = re.sub(r'data-price="[^"]*"', f'data-price="{price}"', box, count=1)
    else:
        box = box.replace('<div class="pf-product"', f'<div class="pf-product" data-price="{price}"', 1)
    box = re.sub(r'\s*data-old="[^"]*"', '', box)
    if info["old"]:
        box = box.replace(f'data-price="{price}"', f'data-price="{price}" data-old="{fmt(info["old"])}"', 1)
    box = re.sub(r'<span class="pf-price">[^<]*</span>', f'<span class="pf-price">~${price}</span>', box, count=1)
    return box


def update_content(html: str, prices: dict) -> tuple[str, list]:
    changes = []
    boxes = list(BOX_RE.finditer(html))
    out, last = [], 0
    for m in boxes:
        box = m.group(0)
        links = box_keys(box)
        info = next((prices[l] for l in links if l in prices and ("price" in prices[l] or prices[l].get("notfound"))), None)
        out.append(html[last:m.start()])
        if info:
            new = update_box(box, info)
            if new != box:
                old_p = re.search(r'data-price="([^"]*)"', box)
                changes.append(f"{old_p.group(1) if old_p else '?'} -> {fmt(info['price']) if 'price' in info else 'Check price'}")
            out.append(new)
        else:
            out.append(box)
        last = m.end()
    out.append(html[last:])
    html = "".join(out)
    # single-product posts: fix the "around $X" price-check sentence
    if len(boxes) == 1:
        info = next((prices[l] for l in box_keys(boxes[0].group(0)) if l in prices), None)
        if info and "price" in info:
            html = re.sub(r'(on sale for around <b>)\$[\d.,]+(</b>)', rf'\g<1>${fmt(info["price"])}\g<2>', html)
        elif info and info.get("notfound"):
            html = re.sub(r'When we looked, this was on sale for around <b>\$[\d.,]+</b>\.\s*', '', html)
    for pattern, repl in TEXT_FIXES:
        html = pattern.sub(repl, html)
    return html, changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    svc = pw.blogger_service()
    posts, token = [], None
    while True:
        r = svc.posts().list(blogId=pw.BLOG_ID, maxResults=50, fetchBodies=True, pageToken=token, status=["LIVE", "DRAFT"]).execute()
        posts += r.get("items", [])
        token = r.get("nextPageToken")
        if not token:
            break
    links = collect_keys(posts)
    print(f"{len(posts)} posts, {len(links)} unique AliExpress links\nFetching US prices:")
    prices = fetch_prices(links)
    json_path = pw.ROOT / "output" / "prices.json"
    json_path.parent.mkdir(exist_ok=True)
    json_path.write_text(json.dumps(prices, indent=1))

    print("\nPost changes:")
    for p in posts:
        new_html, changes = update_content(p["content"], prices)
        new_title = TITLE_FIXES.get(p["title"], p["title"])
        if new_html == p["content"] and new_title == p["title"]:
            continue
        print(f"- {p['title'][:60]}: {', '.join(changes) or 'text only'}")
        if new_title != p["title"]:
            print(f"    title -> {new_title}")
        if a.apply:
            body = {"content": new_html}
            if new_title != p["title"]:
                body["title"] = new_title
            svc.posts().patch(blogId=pw.BLOG_ID, postId=p["id"], body=body).execute()
            time.sleep(1)
    if not a.apply:
        print("\nDry run only. Run with --apply to update Blogger.")


if __name__ == "__main__":
    sys.exit(main())
