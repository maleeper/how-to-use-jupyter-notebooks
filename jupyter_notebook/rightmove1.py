# Full outcode scrape (self-contained) -> rm_wm_property.csv
import re
import json
import time
from typing import List, Dict, Optional
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
    try:
        m = re.search(r"/properties/(\d+)", url)
        if m:
            result["property_id"] = m.group(1)
        r = SESSION.get(url, timeout=30)
        r.raise_for_status()
        html = r.text
        soup = BeautifulSoup(html, "html.parser")
        # price
        price_el = soup.select_one("[data-testid='price']") or soup.select_one(".property-header-price")
        if price_el:
            result["price"] = price_el.get_text(" ", strip=True)
        # address
        addr_el = soup.select_one("[data-testid='address']") or soup.select_one(".address, [itemprop='address']")
        if addr_el:
            result["address"] = addr_el.get_text(" ", strip=True)
        # title-derived fields
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
        # features
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
        # tenure / council tax via dt/dd pairs
        for dt in soup.select("dt"):
            key = dt.get_text(strip=True).upper()
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            val = dd.get_text(" ", strip=True)
            if "TENURE" in key and not result["tenure"]:
                result["tenure"] = val
            if "COUNCIL TAX" in key and not result["council_tax_band"]:
                m2 = re.search(r"Band\s*:?\s*([A-H])", val, re.I)
                result["council_tax_band"] = (m2.group(1).upper() if m2 else val)
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


# ---------- Run full scrape ----------
OUTCODES = load_outcodes()
print(f"Total outcodes to scrape: {len(OUTCODES)}")

all_frames: List[pd.DataFrame] = []
for i, oc in enumerate(OUTCODES, 1):
    print(f"\n[{i}/{len(OUTCODES)}] OUTCODE {oc}")
    df = paginate_outcode(oc, max_pages=200)
    if df.empty:
        continue
    df["outcode"] = oc
    # Derive outward from address if present
    if "address" in df.columns:
        df["district"] = df["address"].apply(extract_outward_postcode)
    else:
        df["district"] = oc
    all_frames.append(df)

if all_frames:
    results_df = pd.concat(all_frames, ignore_index=True)
    if "property_id" in results_df.columns:
        results_df = results_df.drop_duplicates(subset=["property_id"])  # dedupe
    # Insert outcode after property_id if both exist
    cols = list(results_df.columns)
    if "outcode" in cols and "property_id" in cols:
        cols.remove("outcode")
        insert_at = cols.index("property_id") + 1
        cols.insert(insert_at, "outcode")
        results_df = results_df[cols]
    out_path = "rm_wm_property.csv"
    results_df.to_csv(out_path, index=False)
    print(f"Saved -> {out_path} ({len(results_df)} rows)")
else:
    print("No data scraped.")

