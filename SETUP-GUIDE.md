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
| **Find Products** | Keyword ekak gahala AliExpress products hoyanawa → filters (price, orders, rating) → tick karala **Add to queue** |
| **Queue** | Post queue eka (blog ekata yana ewa) saha Pin queue eka |
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
6. **New Posts** eke link boxes yata thiyena board dropdown eken board eka thoranna. **Don't pin** thorannoth pin wenne naha.

**Pin image:** Tool eka product photo eken **1000×1500 (2:3)** pin image ekak automatic hadanawa (title, price, rating, blog URL ekka).

**Pin Queue:** Pins okkoma ekawara yanne naha. **Minute 90 kata ekak** wage yanawa (`.env` eke `PIN_INTERVAL_MIN` eken wenas karanna puluwan). **Pin Queue** tab eken balanna. Pins yanna nam dashboard eka (kalu window eka) open thiyenna one. Close kalath queue eka save wela thiyenawa, aye open kalama ithuru ewa yanawa.

Pin eke link eka blog post ekata yanawa, image eka product image eka. **Save as drafts** walata pin wenne naha (draft ekata link ekak naha).

## Find Products (bulk import) 🔍
Links nathuwa products hoyanna:
1. **Find Products** tab → keyword eka (udaharanayakata `kitchen gadgets`) → **Search**
2. Filters: **Max $**, **Min orders**, **Min positive %**, **Sort** (Best selling / Biggest discount)
3. Hoda products tick karanna (quality warning thiyena ewa auto tick wenne naha). Title / labels edit karanna puluwan.
4. **Publish** / **Draft** thoranna, Pinterest board eka thoranna → **Add to queue**
5. **Load more** eken thawa products

**Post queue:** Blogger eka spam kiyala block nowenna, posts ekawara yanne naha:
- **Minute 20 kata** post ekak (`POST_INTERVAL_MIN`)
- Paya 24 kata **uparima 25** (`DAILY_POST_LIMIT`)
- Publish unama board ekak thoralanam pin ekath pin queue ekata yanawa
- Kalin dapu / queue eke thiyena products aye add wenne naha

Dashboard eka open thiyena welawata witharai queue eka wada karanne.

## Daily auto price update 🔄
Dashboard eka open thiyenawa nam **dawasakata parak** posts okkogema prices AliExpress API eken automatic update wenawa. **Price Update** tab eke **Daily auto update** card eken balanna, **Run now** eken ona welawaka run karanna puluwan.

**Unavailable products:** Product ekak dawas **3k digatama** "not found" unoth eka **Unavailable products** list eke pennanawa. Balala **Move to draft** click karanna.

| `.env` | Karana de |
|---|---|
| `AUTO_PRICE_UPDATE=true` | Daily update eka on / off |
| `UNAVAILABLE_DAYS=3` | Dawas kiyakata passe unavailable kiyala pennanawada |
| `AUTO_DRAFT_UNAVAILABLE=false` | `true` kaloth unavailable posts automatic draft wenawa |

> ⚠️ AliExpress app eka **Test** status eke thiyenakan `AUTO_DRAFT_UNAVAILABLE=false` thiyanna. Test status eke vikunana products samahara ewath "not found" enawa, ethakota hoda posts draft wenna puluwan.

## ☁️ Cloud: laptop eka off unath wada karanna (free)
GitHub Actions eka **minute 20 kata parak** queue eken post ekak, pin ekak, saha dawasakata parak price update eka karanawa. Queue eka GitHub eke **`state`** branch eke save wenawa. Dashboard eka (laptop) products hoyala queue ekata danna witharai.

**Eka parak setup:**
1. `python setup_cloud.py` → `state` branch eka hadala `.env` eke `CLOUD_SYNC=true` karanawa
2. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:
   | Secret | Value |
   |---|---|
   | `ALI_APP_KEY` | `.env` eke ALI_APP_KEY |
   | `ALI_APP_SECRET` | `.env` eke ALI_APP_SECRET |
   | `BLOGGER_TOKEN_JSON` | `token.json` file eke **mulu content eka** |
   | `PINTEREST_ACCESS_TOKEN` | (Pinterest approve unama) |
3. **Google Cloud Console → OAuth consent screen → Publish app** (nathnam Google login eka dawas 7kin expire wenawa)
4. Dashboard eka restart karanna. Repo eke **Actions** tab eken runs balanna. **Run workflow** eken ona welawaka run karanna puluwan.

> Secrets git ekata yanne naha, encrypt wela thiyenne. GitHub schedule eka samahara welawata minute kihipayak paramaadai.

## 🌐 Online: phone eken / ona thanaka idan link ekakin use karanna (free)
Dashboard eka **Render** (free) eke run wenawa, **password** ekakin lock karala. Posting, pins, price update tika
kalin wage **GitHub Actions** eken wenawa, e nisa Render eka sleep unath posts nawathinne naha.

> Mulinma uda thiyena **☁️ Cloud** setup eka karala thiyenna one (`state` branch eka).

**1. GitHub token ekak hadanna** (dashboard ekata queue eka save karanna)
1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. **Repository access:** *Only select repositories* → `blogger-automate`
3. **Permissions → Contents: Read and write**
4. Token eka copy karaganna

**2. Render eke deploy karanna**
1. https://render.com → **GitHub eken sign up** wenna
2. **New → Blueprint** → `blogger-automate` repo eka thoranna (`render.yaml` eka automatic gannawa)
3. Illana values danna:
   | Value | Mokakda |
   |---|---|
   | `APP_PASSWORD` | Oyage dashboard password eka (diga, amaru ekak, wenath thanaka use nokarapu) |
   | `GITHUB_TOKEN` | Step 1 eke token eka |
   | `ALI_APP_KEY`, `ALI_APP_SECRET`, `ALI_TRACKING_ID` | `.env` eke values |
   | `BLOGGER_TOKEN_JSON` | `token.json` file eke **mulu content eka** |
   | `PINTEREST_ACCESS_TOKEN` | Pinterest token eka (nathnam his thiyanna) |
4. **Apply** → build eka iwara unama link ekak labenawa, udaharanayakata `https://pennywise-dashboard.onrender.com`
5. Phone eken eka open karala password eka gahanna. Browser eke **Add to Home screen** karoth app ekak wage pennanawa.

**Danaganna:**
- Free plan eke minute 15k kawuruth use nokaloth server eka **sleep** wenawa. Aye open karaddi **minute 1k witara** yanawa load wenna. Posts / pins walata eka balapanne naha.
- Code eka GitHub ekata push kalama Render eka automatic aluth version eka deploy karanawa.
- Password eka wenas karanna: Render → service eka → **Environment → APP_PASSWORD**. Waradi password **5 parak** gahuwoth minute 10k lock wenawa.
- Pinterest **Connect Pinterest** (OAuth) online use karanawa nam Render eke `PUBLIC_URL` = oyage Render link eka danna, Pinterest app eke Redirect URI ekatath `https://<oyage-link>/api/pinterest/callback` add karanna.
- Google login eka expire unoth: laptop eke dashboard eka eka parak run karala, aluth `token.json` eka Render eke `BLOGGER_TOKEN_JSON` ekatai GitHub secret ekatai danna.

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
