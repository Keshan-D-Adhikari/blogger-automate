"""
Builds a tall 1000x1500 Pinterest image (same look as the hand-made pins):
dark gradient, label pill, title, price line, product photo, rating badge, blog URL band.

  python pin_image.py <image_url> "Title" 12.99   -> output/pin-test.png
"""
import io
import sys

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1000, 1500
# Windows fonts on the laptop, DejaVu on the GitHub Actions runner (Ubuntu)
FONT_BOLD = ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONT = ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
FONT_SYMBOL = ["C:/Windows/Fonts/seguisym.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
TOP, BOTTOM = (38, 16, 34), (130, 32, 66)   # wine gradient
PINK, BRAND = (255, 196, 214), (109, 74, 255)
SITE = "pennywisefinds.blogspot.com"

LABEL_FOR = [  # (blog label, pill text)
    ("Fashion", "STYLE FIND"), ("Beauty", "BEAUTY FIND"), ("Kitchen", "KITCHEN FIND"),
    ("Home", "HOME FIND"), ("Organization", "HOME FIND"), ("Tech", "TECH FIND"),
    ("Halloween", "HALLOWEEN FIND"), ("Gift Ideas", "GIFT IDEA"),
]


def _font(paths, size):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw, text, font, max_w, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_w:
            lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
        lines[-1] += "…"
    return [l for l in lines if l]


def _center(draw, y, text, font, fill):
    draw.text(((W - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def pill_text(labels):
    for label, text in LABEL_FOR:
        if label in (labels or []):
            return text
    return "BUDGET FIND"


def make_pin(title: str, image_url: str, price: float = 0, rating: float = 0, labels=None) -> bytes:
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):  # vertical gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))

    # label pill
    pf = _font(FONT_BOLD, 30)
    pill = pill_text(labels)
    pw = d.textlength(pill, font=pf) + 60
    d.rounded_rectangle([(W - pw) / 2, 72, (W + pw) / 2, 134], radius=31, fill=(214, 72, 104))
    _center(d, 82, pill, pf, "white")

    # title (shrinks to fit 2 lines)
    name = title.split(":")[0].strip()
    for size in (84, 74, 64, 56):
        tf = _font(FONT_BOLD, size)
        lines = _wrap(d, name, tf, 900, 2)
        if all(d.textlength(l, font=tf) <= 900 for l in lines) and not lines[-1].endswith("…"):
            break
    y = 160
    for i, line in enumerate(lines):
        _center(d, y, line, tf, PINK if i == len(lines) - 1 and len(lines) > 1 else "white")
        y += int(size * 1.15)
    if price:
        _center(d, y + 14, f"Only ~${price:.2f} · ships to the US", _font(FONT_BOLD, 40), "white")

    # product photo, cover-cropped into a rounded box
    box = (50, 520, 950, 1370)
    bw, bh = box[2] - box[0], box[3] - box[1]
    try:
        r = requests.get(image_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        photo = Image.open(io.BytesIO(r.content)).convert("RGB")
        scale = max(bw / photo.width, bh / photo.height)
        photo = photo.resize((int(photo.width * scale) + 1, int(photo.height * scale) + 1), Image.LANCZOS)
        left, top = (photo.width - bw) // 2, (photo.height - bh) // 2
        photo = photo.crop((left, top, left + bw, top + bh))
    except Exception:
        photo = Image.new("RGB", (bw, bh), (241, 239, 247))
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle([box[0], box[1] + 12, box[2], box[3] + 12], radius=28, fill=110)
    img.paste((10, 4, 10), mask=shadow.filter(ImageFilter.GaussianBlur(18)))
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, bw, bh], radius=28, fill=255)
    img.paste(photo, box[:2], mask)

    # rating badge
    if rating:
        d = ImageDraw.Draw(img)
        rf, sf = _font(FONT_BOLD, 38), _font(FONT_BOLD, 22)
        rt = f"{rating:.1f} rating"
        star = _font(FONT_SYMBOL, 38)
        sw = d.textlength("★ ", font=star)
        bw2 = max(sw + d.textlength(rt, font=rf), d.textlength("buyer reviews", font=sf)) + 50
        d.rounded_rectangle([box[2] - 16 - bw2, box[1] + 30, box[2] - 16, box[1] + 132], radius=18,
                            fill="white", outline=(225, 220, 240), width=2)
        d.text((box[2] - 16 - bw2 + 25, box[1] + 40), "★ ", font=star, fill=(232, 162, 12))
        d.text((box[2] - 16 - bw2 + 25 + sw, box[1] + 40), rt, font=rf, fill=(30, 27, 70))
        d.text((box[2] - 16 - bw2 + 25 + (bw2 - 50 - d.textlength("buyer reviews", font=sf)) / 2, box[1] + 92),
               "buyer reviews", font=sf, fill=BRAND)

    # site band
    d = ImageDraw.Draw(img)
    d.rectangle([0, 1414, W, H], fill=BRAND)
    _center(d, 1434, SITE, _font(FONT_BOLD, 34), "white")

    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


if __name__ == "__main__":
    from publish import OUT
    OUT.mkdir(exist_ok=True)
    (OUT / "pin-test.png").write_bytes(make_pin(sys.argv[2], sys.argv[1], float(sys.argv[3]), 4.8, ["Kitchen"]))
    print(OUT / "pin-test.png")
