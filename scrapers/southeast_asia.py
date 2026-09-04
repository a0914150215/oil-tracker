"""
Southeast Asia retail fuel & commodity scraper
Sources: Philippines DOE, Indonesia ESDM/Pertamina, MPOB CPO
"""
import httpx, json, re
from bs4 import BeautifulSoup
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OilTracker/1.0)"}
T = httpx.Timeout(20.0)

def _get(url):
    with httpx.Client(headers=HEADERS, timeout=T, follow_redirects=True) as c:
        return c.get(url)

def scrape_philippines_doe() -> dict:
    result = {"source": "Philippines DOE", "data": {}}
    try:
        r = _get("https://www.doe.gov.ph/price-watch")
        soup = BeautifulSoup(r.text, "lxml")
        rows_found = []
        for table in soup.select("table")[:3]:
            for row in table.select("tr"):
                cells = [td.get_text(strip=True) for td in row.select("td,th")]
                if any("diesel" in c.lower() or "gasoline" in c.lower() for c in cells):
                    rows_found.append(cells)
        result["price_rows"] = rows_found[:6]
        headlines = []
        for a in soup.select("h2 a, h3 a, .field-title a")[:10]:
            t = a.get_text(strip=True)
            if any(kw in t.lower() for kw in ["price","diesel","gasoline","rollback","increase"]):
                headlines.append(t)
        result["headlines"] = headlines
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_indonesia_b50() -> dict:
    result = {"source": "Indonesia ESDM / Pertamina", "data": {}, "headlines": []}
    try:
        r = _get("https://www.esdm.go.id/en/")
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("h2 a, h3 a, .news-title a")[:15]:
            t = a.get_text(strip=True)
            if any(kw in t.lower() for kw in ["b50","biodiesel","solar","bbm","pertamina","fuel"]):
                result["headlines"].append(t)
        r2 = _get("https://www.pertamina.com/en/news-room/news-release")
        soup2 = BeautifulSoup(r2.text, "lxml")
        for a in soup2.select("h2 a, h3 a")[:10]:
            t = a.get_text(strip=True)
            if any(kw in t.lower() for kw in ["fuel","price","b50","biodiesel"]):
                result["headlines"].append(t)
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_mpob_cpo() -> dict:
    result = {"source": "MPOB / Bursa CPO", "data": {}}
    try:
        r = _get("https://www.bursamalaysia.com/market_information/quotes/derivatives")
        soup = BeautifulSoup(r.text, "lxml")
        text_blocks = [el.get_text(" ", strip=True) for el in soup.select("td,span,.price")]
        mentions = [t[:100] for t in text_blocks if "CPO" in t or ("palm" in t.lower() and re.search(r"\d{3,4}",t))]
        result["data"]["mentions"] = mentions[:5]
        # Fallback: investing.com palm oil page text
        r2 = _get("https://www.investing.com/commodities/palm-oil")
        soup2 = BeautifulSoup(r2.text, "lxml")
        price_el = soup2.select_one('[data-test="instrument-price-last"]')
        if price_el:
            result["data"]["price_myr"] = price_el.get_text(strip=True)
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_all_sea() -> dict:
    print("  [sea] Philippines DOE...")
    ph = scrape_philippines_doe()
    print("  [sea] Indonesia B50...")
    id_ = scrape_indonesia_b50()
    print("  [sea] MPOB CPO...")
    my = scrape_mpob_cpo()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "philippines_doe": ph,
        "indonesia_b50": id_,
        "malaysia_cpo": my,
    }

if __name__ == "__main__":
    print(json.dumps(scrape_all_sea(), indent=2, ensure_ascii=False))
