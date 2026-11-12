#!/usr/bin/env python3
"""
EW Soundi feedi vahesamm.

Loeb EW Soundi Meta feedi (XML voi CSV, URL voi fail), lisab kategooria custom labelid,
renderdab koigile laos olevatele toodetele EW malliga pildid (PNG) ja kirjutab uue feedi,
kus image_link viitab renderdatud pildile.

Kasutus:
  pip install playwright && playwright install chromium
  python3 build_feed.py --out out --base-url https://sinu-host.ee/ewsound

Testimiseks ilma shop.ewsound.ee ligipaasuta:
  python3 build_feed.py --feed feed.xml --out test --limit 6 --image-override naidis.jpg
"""
import argparse, base64, csv, hashlib, html, io, mimetypes, os, re, sys, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
FEED_URL = "http://shop.ewsound.ee/facebookproductadc967bd35c80a389952e51a8ca7411d5c.et.ee.shop1.xml"
TEMPLATE_VERSION = "1"  # muuda, kui malli kujundust muudad: siis renderdatakse koik uuesti

# Laoseisu silt toote kohal (kuvatakse koigil laos olevatel toodetel). Tuhjaks -> silti ei joonistata.
STOCK_TEXT = "Laos Tallinnas"
# "AMETLIK MAALETOOJA" rida kuvatakse ainult nende brandide juures (väiketähtedega, feedi brand-välja järgi).
# Allikas: EW Soundi poe kirjeldus ("Shure, JBL Professional, Neutrik, Klotz, Soundcraft, Lexicon, Tascam, Monacor ... maaletooja").
OFFICIAL_BRANDS = {"shure", "jblpro", "jbl professional", "neutrik", "klotz", "soundcraft", "lexicon", "tascam", "monacor"}
OFFICIAL_TEXT = "AMETLIK MAALETOOJA"

# ---------------------------------------------------------------- kategooriad
# Feedi product_type on tee "Helitehnika ja PA > Mikrofonid > Vokaalmikrofonid". Reeglid vaatavad tee osi (väiketähtedega).
# Jarjekord loeb: esimene sobiv reegel votab toote. Silt tuleb pildile ja custom_label_0 vaartuseks.
def _eq(*names):
    return lambda segs: any(s in names for s in segs)

def _has(*words):
    return lambda segs: any(w in s for s in segs for w in words)

SEGMENTS = [
    ("Mikrofoni tarvikud", _eq("mikrofonide tarvikud")),
    ("Juhtmevabad mikrofonid", _eq("juhtmevabad mikrofonid")),
    ("Mikrofonid", _eq("mikrofonid", "stuudio mikrofonid")),
    ("Kõrvaklapid", _eq("kõrvaklapid")),
    ("Võimendid", _eq("võimendajad")),
    ("Kastid ja kotid", _has("kõlari kotid", "kastid, kotid")),
    ("Kõlarid", _has("kõlar")),
    ("Stuudiomonitorid", _eq("stuudio monitorid")),
    ("Mikserpuldid", _eq("pa mikserid")),
    ("Stuudiotehnika", _eq("stuudiotehnika")),
    ("Heliseadmed", _eq("heliseadmed")),
    ("PA süsteemid", _eq("pa süsteemid")),
    ("Statiivid", _eq("statiivid")),
    ("Kaablid ja pistikud", _eq("pistikud, kaablid ja tarvikud")),
]


def segment_of(ptype):
    segs = [x.strip().lower() for x in (ptype or "").split(">")]
    for name, pred in SEGMENTS:
        if pred(segs):
            return name
    return ""


def money(s):
    """'74.95 EUR' -> 74.95"""
    if not s:
        return None
    m = re.search(r"[\d.,]+", s)
    return float(m.group(0).replace(",", ".")) if m else None


def split_price(v):
    cents = int(round(v * 100))
    return str(cents // 100), "%02d" % (cents % 100)


def fmt_old(v):
    return ("%.2f" % v).replace(".", ",") + " €"


# ---------------------------------------------------------------- pildid
def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 KlewerFeedTool"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        ctype = r.headers.get_content_type()
    return "data:%s;base64,%s" % (ctype, base64.b64encode(data).decode())


def local_data_uri(path):
    ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        return "data:%s;base64,%s" % (ctype, base64.b64encode(f.read()).decode())


def b64font(fn):
    for d in (os.path.join(HERE, "fonts"), HERE):  # fondid kaustas fonts/ voi otse repo juures
        path = os.path.join(d, fn)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
    raise SystemExit("Fonti ei leitud: " + fn)



def font_css():
    latin = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
    ext = "U+0100-02AF,U+0304,U+0308,U+0329,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF"
    out = []
    for w in (500, 600, 700, 800):
        for sub, rng in (("latin", latin), ("latin-ext", ext)):
            fn = "montserrat-%s-%d-normal.woff2" % (sub, w)
            out.append("@font-face{font-family:'Montserrat';font-weight:%d;src:url(data:font/woff2;base64,%s) format('woff2');unicode-range:%s}"
                       % (w, b64font(fn), rng))
    return "".join(out)


# ---------------------------------------------------------------- mall (EW kataloogimall, 1080 x 1350 / 1080)
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#EEF1F3}
#root{position:relative;width:1080px;height:var(--H);background:#EEF1F3;color:#082437;overflow:hidden;font-family:Montserrat,Arial,sans-serif}
.logo{position:absolute;left:44px;top:40px;height:92px;mix-blend-mode:multiply}
.logotxt{position:absolute;left:48px;top:48px;font-weight:800;font-size:40px;line-height:1.05;letter-spacing:1px}
.logotxt small{display:block;font-weight:600;font-size:22px;letter-spacing:4px;color:#0F94B9}
.cat{position:absolute;right:48px;top:52px;border:3px solid #082437;padding:10px 20px;font-weight:800;font-size:28px;letter-spacing:1.5px;text-transform:uppercase;white-space:nowrap}
.card{position:absolute;left:48px;top:150px;width:984px;height:var(--CH);background:#fff;border-radius:10px;overflow:hidden}
.card .pic{position:absolute;left:112px;right:112px;top:var(--IT);bottom:var(--IB);display:flex;align-items:center;justify-content:center}
.card .pic img{max-width:100%;max-height:100%;object-fit:contain}
.badge{position:absolute;right:40px;top:0;background:#0F94B9;color:#fff;font-weight:800;font-size:60px;padding:16px 26px;letter-spacing:-1px}
.stock{position:absolute;left:36px;top:34px;font-weight:700;font-size:27px;background:#E6F4F8;border-radius:40px;padding:10px 22px 10px 18px;display:flex;align-items:center;gap:12px}
.stock i{width:16px;height:16px;border-radius:50%;background:#1DB36B;display:block}
.bar{position:absolute;left:48px;top:var(--BT);width:984px;height:200px;display:flex;border-radius:10px;overflow:hidden}
.nm{flex:1;background:#fff;padding:0 36px;display:flex;flex-direction:column;justify-content:center;min-width:0}
.nm b{font-weight:800;font-size:50px;line-height:1.1;white-space:nowrap}
.nm span{font-size:30px;font-weight:500;color:#232022;margin-top:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nm em{font-style:normal;font-size:22px;font-weight:700;color:#0F94B9;margin-top:10px;letter-spacing:.5px}
.pr{width:400px;background:#082437;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:0 24px}
.old{font-size:34px;font-weight:600;color:#9FB3C2;position:relative}
.old:after{content:'';position:absolute;left:-4px;right:-4px;top:50%;height:4px;background:#0F94B9;transform:rotate(-12deg)}
.now{font-weight:800;font-size:var(--PS);letter-spacing:-3px;line-height:1;display:flex;align-items:flex-start;white-space:nowrap}
.now sup{font-size:40px;letter-spacing:0;margin-top:10px;margin-left:4px}
"""

FIT_JS = """()=>{const b=document.querySelector('.nm b');if(!b)return;let s=50;b.style.fontSize=s+'px';
while(b.scrollWidth>b.clientWidth&&s>36){s-=2;b.style.fontSize=s+'px'}
if(b.scrollWidth>b.clientWidth){b.style.whiteSpace='normal';b.style.display='-webkit-box';
b.style.webkitLineClamp='2';b.style.webkitBoxOrient='vertical';b.style.overflow='hidden';b.style.fontSize='34px'}}"""


def card_html(p, logo_uri):
    logo = ('<img class="logo" src="%s">' % logo_uri) if logo_uri else \
        '<div class="logotxt">EW SOUND<small>&amp; LIGHT</small></div>'
    cat = '<div class="cat">%s</div>' % html.escape(p["seg"]) if p["seg"] else ""
    badge = '<div class="badge">-%d%%</div>' % p["disc"] if p["disc"] else ""
    stock = '<div class="stock"><i></i>%s</div>' % html.escape(STOCK_TEXT) if STOCK_TEXT else ""
    sub = '<span>%s</span>' % html.escape(p["sub"]) if p["sub"] else ""
    off = '<em>%s</em>' % html.escape(OFFICIAL_TEXT) if p["official"] else ""
    old = '<div class="old">%s</div>' % html.escape(p["old"]) if p["old"] else ""
    return ('%s%s<div class="card"><div class="pic"><img src="%s"></div>%s%s</div>'
            '<div class="bar"><div class="nm"><b>%s</b>%s%s</div>'
            '<div class="pr">%s<div class="now">%s<sup>,%s&nbsp;€</sup></div></div></div>'
            % (logo, cat, p["img"], badge, stock, html.escape(p["name"]), sub, off, old, p["new_i"], p["new_c"]))


def read_feed(src):
    if re.match(r"https?://", src):
        raw = urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "KlewerFeedTool"}), timeout=60).read()
    else:
        raw = open(src, "rb").read()
    text = raw.decode("utf-8-sig")
    if text.lstrip().startswith("<"):
        return read_xml(text)
    return list(csv.DictReader(io.StringIO(text)))


XML_ALIASES = {"image": "image_link", "product_id": "id", "name": "title", "url": "link", "stock": "availability"}


def read_xml(text):
    """Meta/Google tooteXML (RSS 2.0 g: nimeruumiga voi lihtne <product>/<item>/<entry>) -> list of dict."""
    import xml.etree.ElementTree as ET
    local = lambda t: t.rsplit("}", 1)[-1].lower()
    root = ET.fromstring(text.encode("utf-8"))
    rows = []
    for el in root.iter():
        if local(el.tag) in ("item", "entry", "product") and len(list(el)) > 3:
            row = {}
            for ch in el:
                k = XML_ALIASES.get(local(ch.tag), local(ch.tag))
                v = (ch.text or "").strip()
                if len(ch) and local(ch.tag) == "shipping":  # <g:shipping><g:country/><g:price/></g:shipping> -> CSV "EE:::0.00 EUR"
                    sub = {local(x.tag): (x.text or "").strip() for x in ch}
                    v = "%s:%s:%s:%s" % (sub.get("country", ""), sub.get("region", ""), sub.get("service", ""), sub.get("price", ""))
                if k in row and k.startswith("additional_image"):
                    row[k] += "," + v
                elif k not in row or not row[k]:
                    row[k] = v
            rows.append(row)
    for r in rows:
        for k in ("id", "title", "price", "sale_price", "link", "image_link", "brand", "availability", "description"):
            r.setdefault(k, "")
        if not r["availability"]:
            r["availability"] = "in stock"
    if not rows:
        raise SystemExit("XML feedist ei leitud tooteid (item/entry/product)")
    return rows




def short_sub(r):
    """Alamrida: kirjeldus ainult siis, kui see on lühike ühe rea tekst (nt "Windscreen")."""
    d, t, b = (r.get("description") or "").strip(), r["title"].lower(), (r.get("brand") or "").lower()
    if d and "\n" not in d and len(d) <= 34 and d.lower() not in t and not (b and d.lower().startswith(b)):
        return d
    return ""


def category_leaf(r):
    """Alapealkiri (alamkategooria) feedi enda kategooriaveergudest, kui need on olemas."""
    for k in ("product_type", "google_product_category", "category", "categoryid"):
        v = (r.get(k) or "").strip()
        if v and not v.isdigit():
            return re.split(r"\s*(?:>|/)\s*", v)[-1]
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=FEED_URL, help="feedi URL voi fail (XML voi CSV)")
    ap.add_argument("--out", default="out", help="valjundkaust (images/ ja feed.csv)")
    ap.add_argument("--base-url", default="https://EXAMPLE.ee/ewsound", help="URL, kust renderdatud pildid avalikult kattesaadavad on")
    ap.add_argument("--formats", default="1x1", help="1x1, 4x5 voi 1x1,4x5 (feedi image_link kasutab esimest)")
    ap.add_argument("--min-discount", type=int, default=5, help="allahindluse mark kuvatakse alates sellest %%-st")
    ap.add_argument("--segments-only", action="store_true", help="renderda ainult kategooriaga tooted (vaikimisi koik in stock tooted)")
    ap.add_argument("--limit", type=int, default=0, help="renderda ainult N esimest (test)")
    ap.add_argument("--image-override", help="kasuta seda kohalikku pilti koigi toodete asemel (test)")
    ap.add_argument("--no-render", action="store_true", help="ainult feed, ilma piltideta")
    a = ap.parse_args()

    rows = read_feed(a.feed)
    os.makedirs(os.path.join(a.out, "images"), exist_ok=True)
    formats = [f.strip() for f in a.formats.split(",") if f.strip()]
    H = {"1x1": 1080, "4x5": 1350}

    # 1) rikastamine
    for r in rows:
        r["title"] = html.unescape(r["title"]).strip()
        seg = segment_of(r.get("product_type"))
        price, sale = money(r.get("price")), money(r.get("sale_price"))
        disc = round((1 - sale / price) * 100) if price and sale and sale < price else 0
        r["_seg"], r["_disc"] = seg, disc
        r["custom_label_0"] = seg
        r["custom_label_1"] = "soodus" if disc else "tavahind"
        r["custom_label_2"] = (r.get("brand") or "").strip()
        r["custom_label_3"] = ("40+" if disc >= 40 else "20-40" if disc >= 20 else "5-20" if disc >= 5 else "") if disc else ""

    todo_all = [r for r in rows if (r["_seg"] or not a.segments_only) and r.get("availability") == "in stock"]
    if a.limit:
        todo_all = todo_all[:a.limit]
    imgdir = os.path.join(a.out, "images")
    for r in todo_all:  # failinimes on sisu rasi: muutub hind/pealkiri/pilt -> muutub URL -> Meta tõmbab uue pildi
        key = "|".join([TEMPLATE_VERSION, r["title"], r.get("brand", ""), r["price"], r.get("sale_price", ""), r["_seg"],
                        r["image_link"], str(a.min_discount), STOCK_TEXT, ",".join(sorted(OFFICIAL_BRANDS))])
        r["_h"] = hashlib.sha1(key.encode()).hexdigest()[:10]

    def fname(r, fmt):
        return "%s_%s_%s.png" % (r["id"], r["_h"], fmt)
    todo = [r for r in todo_all if not all(os.path.exists(os.path.join(imgdir, fname(r, f))) for f in formats)]
    print("Tooteid feedis: %d, kategooriaga: %d, pilt vaja kõigile: %d, uusi/muutunud renderdatakse: %d"
          % (len(rows), sum(1 for r in rows if r["_seg"]), len(todo_all), len(todo)))
    for k in SEGMENTS:
        print("  %-18s %d" % (k[0], sum(1 for r in rows if r["_seg"] == k[0])))

    # 2) renderdus
    done = set()
    if not a.no_render and todo:
        from playwright.sync_api import sync_playwright
        logo_path = next((os.path.join(HERE, n) for n in ("logo.png", "logo.svg", "logo.jpg") if os.path.exists(os.path.join(HERE, n))), None)
        logo_uri = local_data_uri(logo_path) if logo_path else None
        if not logo_uri:
            print("HOIATUS: logo.png puudub, kasutan tekstilogot", file=sys.stderr)
        override = local_data_uri(a.image_override) if a.image_override else None

        def get_img(r):
            if override:
                return r["id"], override
            try:
                return r["id"], fetch(r["image_link"])
            except Exception as e:
                print("  pilt ebaonnestus id=%s: %s" % (r["id"], e), file=sys.stderr)
                return r["id"], None

        with ThreadPoolExecutor(8) as ex:
            imgs = dict(ex.map(get_img, todo))

        with sync_playwright() as pw:
            br = pw.chromium.launch()
            page = br.new_page(viewport={"width": 1080, "height": 1350})
            page.set_content("<style>%s%s</style><div id=root></div>" % (font_css(), CSS))
            for i, r in enumerate(todo, 1):
                img = imgs.get(r["id"])
                if not img:
                    continue
                price, sale = money(r["price"]), money(r.get("sale_price"))
                cur = sale if r["_disc"] else price
                ni, nc = split_price(cur)
                brand = (r.get("brand") or "").strip()
                p = dict(seg=r["_seg"], disc=r["_disc"] if r["_disc"] >= a.min_discount else 0,
                         name=r["title"], sub=short_sub(r),
                         official=brand.lower() in OFFICIAL_BRANDS,
                         old=fmt_old(price) if r["_disc"] else "", new_i=ni, new_c=nc, img=img)
                ps = 104 if len(ni) <= 3 else 88 if len(ni) == 4 else 72
                for fmt in formats:
                    h = H[fmt]
                    page.evaluate("""([h,ch,bt,it,ib,ps,html])=>{const r=document.getElementById('root');
                        r.style.setProperty('--H',h+'px');r.style.setProperty('--CH',ch+'px');r.style.setProperty('--BT',bt+'px');
                        r.style.setProperty('--IT',it+'px');r.style.setProperty('--IB',ib+'px');r.style.setProperty('--PS',ps+'px');
                        r.innerHTML=html}""",
                                  [h, h - 430, h - 250, 110 if h > 1100 else 90, 70 if h > 1100 else 30, ps,
                                   card_html(p, logo_uri)])
                    page.evaluate("Promise.all([...document.images].map(i=>i.decode().catch(()=>0)))")
                    page.evaluate("document.fonts.ready")
                    page.evaluate(FIT_JS)
                    page.locator("#root").screenshot(path=os.path.join(imgdir, fname(r, fmt)))
                if i % 50 == 0:
                    print("  %d/%d" % (i, len(todo)))
            br.close()
    if not a.no_render:
        done = {r["id"] for r in todo_all if os.path.exists(os.path.join(imgdir, fname(r, formats[0])))}
    byid = {r["id"]: r for r in todo_all}

    # 3) uus feed
    base = a.base_url.rstrip("/")
    cols = list(rows[0].keys())
    cols = [c for c in cols if not c.startswith("_")]
    for c in ("product_type", "custom_label_0", "custom_label_1", "custom_label_2", "custom_label_3"):
        if c not in cols:
            cols.append(c)
    if "original_image_link" not in cols:
        cols.append("original_image_link")
    with open(os.path.join(a.out, "feed.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r["original_image_link"] = r["image_link"]
            if r["id"] in done:
                r["image_link"] = "%s/images/%s" % (base, fname(byid[r["id"]], formats[0]))
            w.writerow(r)
    print("Valmis: %s/feed.csv, pilte: %d" % (a.out, len(done)))


if __name__ == "__main__":
    main()
