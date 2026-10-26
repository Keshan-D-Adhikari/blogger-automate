# Blogger Automation – Setup Guide (Sinhala)

Me script eka AliExpress links walin product details aragena, **Penny Wise Finds** blog ekata post hadala danawa.

## Step 1 – AliExpress API keys (approve unama)
1. AliExpress Open Platform → **App Management → Create App** → type: **Affiliates API**
2. Labena **App Key** saha **App Secret** copy karaganna
3. AliExpress Portals → **Tracking ID** eka copy karaganna
4. Me folder eke `.env.example` file eka copy karala nama **`.env`** karanna, eke values danna:
```
ALI_APP_KEY=oyage_app_key
ALI_APP_SECRET=oyage_app_secret
ALI_TRACKING_ID=oyage_tracking_id
```
> `.env` file eka kawurutath denna epa, chat ekata danna epa.

## Step 2 – Blogger API (Google Cloud)
1. https://console.cloud.google.com → aluth project: `pennywise-automation`
2. **APIs & Services → Library → Blogger API v3 → Enable**
3. **OAuth consent screen** → External → app name + oyage email → **Test users** walata oyage Gmail eka add karanna
4. **Credentials → Create Credentials → OAuth client ID → Desktop app**
5. **Download JSON** → nama **`client_secret.json`** karala me folder ekata danna

## Step 3 – Check karanna
```
python publish.py --check
```
Okkoma **OK** kiyala enna one.

## Step 4 – Links danna
`links.txt` file eka open karala AliExpress links danna (line ekakata ekak):
```
https://s.click.aliexpress.com/e/_c2R7m1N5
https://s.click.aliexpress.com/e/_c3vHRWZ1 | Home
```
`|` ta passe labels danna puluwan (optional). Script eka title eka balala labels automatic dala denawa.

## Step 5 – Run karanna
| Command | Karana de |
|---|---|
| `python publish.py --dry-run` | Products check karala HTML `output/` ekata save karanawa, blog ekata danne naha |
| `python publish.py` | Blog ekata **draft** widiyata danawa (mama recommend karanne) |
| `python publish.py --publish` | Blog ekata kelinma **publish** karanawa |
| `python publish.py --force` | Quality filter eka skip karanawa |
| `python publish.py --demo` | API keys nathuwa sample post ekak hadanawa |

Mul parak run kalama browser eka open wela **Google login** ekak illanawa. Eka eka parak witharai (`token.json` save wenawa).

## Dashboard (React UI) 🖥️
Command line wenuwata browser eken use karanna:
```
cd ui
npm install
npm run build
cd ..
python server.py
```
Ita passe browser eke **http://127.0.0.1:5050** open karanna.

| Tab | Karana de |
|---|---|
| **New Posts** | Links paste karala **Preview** → title/labels edit karala → **Save as drafts** / **Publish** |
| **Blog Posts** | Blog eke posts okkoma (LIVE / DRAFT) |
| **Price Update** | **Check prices** → wenas wena ewa balala → **Apply changes** |
| **History** | Me tool eken dapu links |

> Ilanga parak UI eka run karanna `python server.py` witharak athi (build eka eka parak witharai).
> Server eka run wenne oyage computer eke (127.0.0.1) witharai, API keys browser ekata yanne naha.

## Pinterest auto pin 📌
**Publish** karaddi post eka Pinterest board ekakatath automatic pin wenawa.

1. https://developers.pinterest.com → Pinterest account eken login → **My apps → Connect app**
2. App eka hadala **App ID** saha **App secret key** copy karaganna
3. App settings eke **Redirect URIs** ekata meka add karanna (hariyatama):
```
http://localhost:5050/api/pinterest/callback
```
4. `.env` ekata danna:
```
PINTEREST_APP_ID=oyage_app_id
PINTEREST_APP_SECRET=oyage_secret
PINTEREST_API=https://api-sandbox.pinterest.com
```
> Mulinma app eka **Trial access** walin thiyenne. Ekedi **sandbox** eka witharai wada karanne, pins penne oyata witharai.
> **Standard access** approve unama `PINTEREST_API=https://api.pinterest.com` karanna. Ethakota pins okkotama penawa.
5. Dashboard eka restart karanna. Wam paththe **Connect Pinterest** click karala allow karanna.
6. **New Posts** eke **Publish** button eka langa board dropdown eken board eka thoranna. **Don't pin** thorannoth pin wenne naha.

Pin eke link eka blog post ekata yanawa, image eka product image eka. **Save as drafts** walata pin wenne naha (draft ekata link ekak naha).

## Quality filter (automatic)
Me ewa thiyena products **skip** karanawa (`.env` eken wenas karanna puluwan):
- Price **$50** ta wadi
- Positive feedback **90%** ta adu
- Orders **10** ta adu

Brand/character names (Top Gun, Zuko, Disney, Pokemon…) title eken automatic ain karanawa.

## Files
| File | Wade |
|---|---|
| `publish.py` | Main script eka |
| `links.txt` | Oya danna links |
| `.env` | API keys (secret) |
| `client_secret.json` | Google OAuth (secret) |
| `token.json` | Google login eka (auto) |
| `pinterest.py` | Pinterest pins |
| `pinterest_token.json` | Pinterest login eka (secret, auto) |
| `published.json` | Danata dapu links (duplicate nowenna) |
| `output/` | Hadapu post HTML |
