# EW Soundi feedi vahesamm

Loeb EW Soundi Meta feedi (XML), lisab kategooria custom labelid, renderdab laos olevatele toodetele EW malliga pildid ja kirjutab uue feedi (`out/feed.csv`), kus `image_link` viitab renderdatud pildile. Algne pilt jääb veergu `original_image_link`.

## Enne esimest jooksu
1. Pane kausta `logo.png` (EW Sound & Light logo, PNG). Ilma selleta kasutatakse tekstilogot.
2. `build_feed.py` algus: kontrolli `STOCK_TEXT` ("Laos Tallinnas"), `OFFICIAL_BRANDS` (brandid, mille juures kuvatakse "AMETLIK MAALETOOJA") ja `SEGMENTS` (kategooriad feedi product_type tee järgi).
3. Kui malli muudad, tõsta `TEMPLATE_VERSION` ühe võrra.

## Käivitamine
    pip install playwright && playwright install chromium
    python3 build_feed.py --out out --base-url https://BUCKETI-AVALIK-URL --formats 1x1

Test: `--limit 6`, `--image-override pilt.jpg`, `--formats 1x1,4x5`.

## Automaatne päevane jooks
Sama mis Popsportil: uus privaatne repo, uus R2 bucket (sama Cloudflare konto), repo Secrets `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, Variables `R2_BUCKET`, `BASE_URL`. Meta andmeallikaks `<BASE_URL>/feed.csv`.
