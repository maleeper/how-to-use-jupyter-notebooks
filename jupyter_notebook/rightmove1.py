# Full outcode scrape (self-contained) -> rm_wm_property.csv
import re
import json
import time
from typing import List, Dict, Optional
import argparse
import sys
from urllib.parse import urlparse, parse_qs

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ---------- Config ----------
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection": "keep-alive",
}
SESSION = requests.Session()
SESSION.headers.update(REQUEST_HEADERS)

PROPERTY_LINK_SELECTORS = [
    "a.propertyCard-link",
    "a.propertyCard-detailsLink",
    "a[data-test='property-card-link']",
    "[data-testid^='propertyCard-'] a.propertyCard-link",
]

# ---------- Helpers ----------

def build_outcode_url(outcode: str) -> str:
    return f"https://www.rightmove.co.uk/property-for-sale/{outcode.upper().strip()}.html"


def add_index(url: str, idx: int) -> str:
    return url + ("&" if urlparse(url).query else "?") + f"index={idx}"


def get_html(url: str) -> Optional[str]:
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None


def get_soup(url: str) -> Optional[BeautifulSoup]:
    html = get_html(url)
    if html is None:
        return None
    return BeautifulSoup(html, "html.parser")


def extract_property_links_html(url: str) -> List[str]:
    soup = get_soup(url)
    if soup is None:
        return []
    links: List[str] = []
    for selector in PROPERTY_LINK_SELECTORS:
        for a in soup.select(selector):
            href = a.get("href")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.rightmove.co.uk" + href
            if "/properties/" in href:
                links.append(href.split("#")[0])
    return sorted(set(links))


def find_outcode_location_identifier_from_html(html: str) -> Optional[str]:
    if not html:
        return None
    m = re.search(r"OUTCODE\^(\d+)", html)
    return f"OUTCODE^{m.group(1)}" if m else None


def extract_property_links_api(li: str, idx: int) -> List[str]:
    params = {
        "locationIdentifier": li,
        "channel": "BUY",
        "index": str(idx),
        "includeSSTC": "true",
        "sortType": "2",
    }
    url = "https://www.rightmove.co.uk/api/_search" \
        + ("?" + "&".join([f"{k}={v}" for k, v in params.items()]))
    try:
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        props = data.get("properties") or []
        links: List[str] = []
        for p in props:
            pid = p.get("id") or p.get("propertyId")
            if pid:
                links.append(f"https://www.rightmove.co.uk/properties/{pid}")
        return links
    except Exception:
        return []


INT_PATTERN = re.compile(r"(\d+)")
SQM_PATTERN = re.compile(r"([0-9,.]+)\s*(sq\s*m|sqm|square\s*metres?)", re.I)
SQFT_PATTERN = re.compile(r"([0-9,.]+)\s*(sq\s*ft|sqft|square\s*feet)\b", re.I)


def first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = INT_PATTERN.search(text)
    return int(m.group(1)) if m else None


def extract_outward_postcode(address: str) -> Optional[str]:
    if not isinstance(address, str) or not address.strip():
        return None
    text = address.upper().strip().rstrip(",.;")
    m = re.search(r"([A-Z]{1,2}\d{1,2}[A-Z]?)\s*\d[ABD-HJLNP-UW-Z]{2}$", text)
    return m.group(1) if m else None


def extract_detail(url: str) -> Dict:
    result: Dict = {
        "url": url,
        "property_id": None,
        "address": None,
        "price": None,
        "property_type": None,
        "bedrooms": None,
        "bathrooms": None,
        "size_sq_m": None,
        "size_sq_ft": None,
        "tenure": None,
        "council_tax_band": None,
        "parking": None,
        "garden": None,
        "key_features": None,
    }
    
    def dd_text(soup: BeautifulSoup, label_contains: str) -> Optional[str]:
        label_u = label_contains.upper()
        for dt in soup.select("dt"):
            key = dt.get_text(strip=True).upper()
            if label_u in key:
                dd = dt.find_next_sibling("dd")
                if dd:
                    p = dd.find("p")
                    if p:
                        return p.get_text(" ", strip=True) or None
                    # join all text in dd to preserve numbers split across lines
                    return " ".join(list(dd.stripped_strings)) or None
        return None

    try:
        # property id from URL
        m = re.search(r"/properties/(\d+)", url)
        if m:
            result["property_id"] = m.group(1)
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        html = r.text
        soup = BeautifulSoup(html, "html.parser")

        # price (include sitemap hint selector)
        price_el = (
            soup.select_one("[itemtype='https://schema.org/Residence'] div article div div div > span:nth-of-type(1)")
            or soup.select_one("[itemtype='https://schema.org/Residence'] span:nth-of-type(1)")
            or soup.select_one("[data-testid='price']")
            or soup.select_one(".property-header-price")
            or soup.select_one(".property-header__price")
            or soup.select_one("[data-test='price']")
        )
        if price_el:
            result["price"] = price_el.get_text(" ", strip=True)
        else:
            # fallback regex scan
            pm = re.search(r"£\s*[\d,]+", html)
            if pm:
                result["price"] = pm.group(0)

        # address (prefer itemprop selector per sitemap)
        addr_el = (
            soup.select_one("div[itemprop='address']")
            or soup.select_one("[data-testid='address']")
            or soup.select_one(".address, [itemprop='address']")
        )
        if addr_el:
            result["address"] = addr_el.get_text(" ", strip=True)

        # dd-based fields
        if result["property_type"] is None:
            t = dd_text(soup, "PROPERTY TYPE")
            if t:
                result["property_type"] = t
        if result["bedrooms"] is None:
            b = dd_text(soup, "BEDROOMS")
            if b:
                result["bedrooms"] = first_int(b)
        if result["bathrooms"] is None:
            bth = dd_text(soup, "BATHROOMS")
            if bth:
                result["bathrooms"] = first_int(bth)

        # size via multiple possible labels
        size_text = (
            dd_text(soup, "SIZE")
            or dd_text(soup, "FLOOR AREA")
            or dd_text(soup, "FLOOR-AREA")
        )
        if size_text:
            m2 = SQM_PATTERN.search(size_text)
            ft2 = SQFT_PATTERN.search(size_text)
            if m2:
                result["size_sq_m"] = m2.group(1).replace(",", "")
            if ft2:
                result["size_sq_ft"] = ft2.group(1).replace(",", "")
        
        # JSON-LD fallback for floor size
        if result["size_sq_m"] is None or result["size_sq_ft"] is None:
            try:
                for script in soup.select('script[type="application/ld+json"]'):
                    try:
                        data = json.loads(script.get_text(strip=True))
                    except Exception:
                        continue
                    nodes = data if isinstance(data, list) else [data]
                    for node in nodes:
                        if isinstance(node, dict):
                            fs = node.get("floorSize")
                            if isinstance(fs, dict):
                                val = fs.get("value") or fs.get("area")
                                unit = (fs.get("unitText") or fs.get("unitCode") or "").lower()
                                if val:
                                    if ("m" in unit or "metre" in unit) and result["size_sq_m"] is None:
                                        result["size_sq_m"] = str(val).replace(",", "")
                                    if ("ft" in unit or "feet" in unit) and result["size_sq_ft"] is None:
                                        result["size_sq_ft"] = str(val).replace(",", "")
            except Exception:
                pass

        # brute-force regex scan over full HTML text if still missing
        if result["size_sq_ft"] is None:
            mft = re.search(r"([0-9,.]+)\s*(sq\s*ft|sqft|square\s*feet)\b", html, re.I)
            if mft:
                result["size_sq_ft"] = mft.group(1).replace(",", "")
        if result["size_sq_m"] is None:
            mm = re.search(r"([0-9,.]+)\s*(sq\s*m|sqm|square\s*metres?)\b", html, re.I)
            if mm:
                result["size_sq_m"] = mm.group(1).replace(",", "")

        # key features from article UL and similar
        feats = []
        for ul_sel in ["ul.key-features", "ul.property-features", "ul[data-test='key-features']", "article ul"]:
            for ul in soup.select(ul_sel):
                for li in ul.select("li"):
                    t = li.get_text(" ", strip=True)
                    if t:
                        feats.append(t)
        if feats:
            seen = set(); ordered = []
            for f in feats:
                if f not in seen:
                    seen.add(f); ordered.append(f)
            result["key_features"] = "; ".join(ordered)



        # tenure / council tax / parking / garden
        if result["tenure"] is None:
            ten = dd_text(soup, "TENURE")
            if ten:
                result["tenure"] = ten
        if result["council_tax_band"] is None:
            ct = dd_text(soup, "COUNCIL TAX")
            if ct:
                mct = re.search(r"Band\s*:?\s*([A-H])", ct, re.I)
                result["council_tax_band"] = (mct.group(1).upper() if mct else ct)
        if result["parking"] is None:
            pk = dd_text(soup, "PARKING")
            if pk:
                result["parking"] = "Yes" if re.search(r"yes|private|drive|garage|off[- ]road|parking", pk, re.I) else pk
        if result["garden"] is None:
            gd = dd_text(soup, "GARDEN")
            if gd:
                result["garden"] = "Yes" if re.search(r"yes|garden|yard|balcony|terrace", gd, re.I) else gd

        # title-derived fallbacks
        title_el = soup.select_one("[data-testid='title']") or soup.select_one("h1")
        if title_el:
            title_text = title_el.get_text(" ", strip=True)
            if result["bedrooms"] is None:
                bm = re.search(r"(\d+)\s*bed", title_text, re.I)
                if bm:
                    result["bedrooms"] = int(bm.group(1))
            if result["property_type"] is None:
                tm = re.search(r"\b(Detached|Semi[- ]?Detached|End of Terrace|Terraced|Flat|Apartment|Bungalow|Cottage|Townhouse)\b", title_text, re.I)
                if tm:
                    result["property_type"] = tm.group(1).replace("-", " ").title()

        # fact chips for beds/baths/sizes
        facts = [el.get_text(" ", strip=True) for el in soup.select("[data-testid='rounded-fact'], .key-fact, .fact")]
        for fact in facts:
            if result["bedrooms"] is None:
                mbed = re.search(r"(\d+)\s*bed", fact, re.I)
                if mbed:
                    result["bedrooms"] = int(mbed.group(1))
            if result["bathrooms"] is None:
                mbath = re.search(r"(\d+)\s*bath", fact, re.I)
                if mbath:
                    result["bathrooms"] = int(mbath.group(1))
            if result["size_sq_ft"] is None:
                mft = SQFT_PATTERN.search(fact)
                if mft:
                    result["size_sq_ft"] = mft.group(1).replace(",", "")
            if result["size_sq_m"] is None:
                mm = SQM_PATTERN.search(fact)
                if mm:
                    result["size_sq_m"] = mm.group(1).replace(",", "")

        return result
    except Exception:
        return result


def paginate_outcode(outcode: str, max_pages: int = 200, delay_s: float = 0.6) -> pd.DataFrame:
    start_url = build_outcode_url(outcode)
    print(f"Start URL: {start_url}")
    html0 = get_html(start_url) or ""
    li = find_outcode_location_identifier_from_html(html0)

    all_rows: List[Dict] = []
    for page_no in range(max_pages):
        idx = page_no * 24
        url = add_index(start_url, idx)
        print(f"  Listing page {page_no+1}/{max_pages}: index={idx}")
        links = extract_property_links_html(url)
        if not links and li:
            links = extract_property_links_api(li, idx)
        if not links:
            print("  No property links found, stopping.")
            break
        print(f"  Found {len(links)} property links")
        for link in links:
            row = extract_detail(link)
            all_rows.append(row)
            time.sleep(delay_s)
        time.sleep(0.8)
    return pd.DataFrame(all_rows)


def load_outcodes() -> List[str]:
    # Prefer existing oc_df if present in the notebook
    if "oc_df" in globals() and isinstance(globals()["oc_df"], pd.DataFrame):
        series = globals()["oc_df"].get("outcode")
        if series is not None:
            outcodes = (series.dropna().astype(str).str.upper().str.replace(r"\s+", "", regex=True).unique().tolist())
            if outcodes:
                return outcodes
    # Fallback to outward_postcodes.csv
    df = pd.read_csv("outward_postcodes.csv")
    for c in ["OutwardPostcode", "Outward Postcode", "outward_postcode", "outcode", "district"]:
        if c in df.columns:
            series = df[c]
            return (series.dropna().astype(str).str.upper().str.replace(r"\s+", "", regex=True).unique().tolist())
    raise ValueError("Could not find an outcode column in outward_postcodes.csv")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Rightmove properties by outward postcode (outcode)")
    parser.add_argument(
        "--outcodes",
        help="Comma-separated list of outcodes to scrape (e.g. 'WR7' or 'B93,B92')",
        default=None,
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=200,
        help="Max pages per outcode (24 results per page)",
    )
    parser.add_argument(
        "--output",
        default="rm_wm_property.csv",
        help="Output CSV path",
    )
    args = parser.parse_args(argv)

    if args.outcodes:
        OUTCODES = [oc.strip().upper().replace(" ", "") for oc in args.outcodes.split(",") if oc.strip()]
    else:
        OUTCODES = load_outcodes()

    print(f"Total outcodes to scrape: {len(OUTCODES)}")

    all_frames: List[pd.DataFrame] = []
    for i, oc in enumerate(OUTCODES, 1):
        print(f"\n[{i}/{len(OUTCODES)}] OUTCODE {oc}")
        df = paginate_outcode(oc, max_pages=args.max_pages)
        if df.empty:
            continue
        df["outcode"] = oc
        all_frames.append(df)

    if not all_frames:
        print("No data scraped.")
        return 1

    results_df = pd.concat(all_frames, ignore_index=True)
    if "property_id" in results_df.columns:
        results_df = results_df.drop_duplicates(subset=["property_id"])  # dedupe
    cols = list(results_df.columns)
    if "outcode" in cols and "property_id" in cols:
        cols.remove("outcode")
        insert_at = cols.index("property_id") + 1
        cols.insert(insert_at, "outcode")
        results_df = results_df[cols]
    out_path = args.output
    results_df.to_csv(out_path, index=False)
    print(f"Saved -> {out_path} ({len(results_df)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

