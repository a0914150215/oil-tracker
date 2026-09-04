"""
Price scraper
- Brent / WTI : EIA open API (免費，無需 key)
- 運費 TD3C   : Freightos Baltic Index + Hellenicshipping
- 柴油裂解    : EIA petroleum prices
"""
import httpx, json, re
from bs4 import BeautifulSoup
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}
T = httpx.Timeout(25.0)


def _get(url, **kw):
    with httpx.Client(headers=HEADERS, timeout=T, follow_redirects=True) as c:
        return c.get(url, **kw)


def scrape_eia_prices() -> dict:
    result = {"source": "EIA open API", "data": {}}
    try:
        url = (
            "https://api.eia.gov/v2/petroleum/pri/spt/data/"
            "?api_key=DEMO_KEY&frequency=weekly"
            "&data[0]=value"
            "&facets[series][]=RBRTE"
            "&facets[series][]=RWTC"
            "&sort[0][column]=period&sort[0][direction]=desc&length=3"
        )
        r = _get(url)
        rows = r.json().get("response", {}).get("data", [])
        for row in rows:
            s, period, val = row.get("series"), row.get("period"), row.get("value")
            if s == "RBRTE" and "brent" not in result["data"]:
                result["data"]["brent"] = {"price": val, "period": period, "unit": "USD/bbl"}
            elif s == "RWTC" and "wti" not in result["data"]:
                result["data"]["wti"] = {"price": val, "period": period, "unit": "USD/bbl"}
    except Exception as e:
        result["error"] = str(e)
    return result


def scrape_eia_products() -> dict:
    result = {"source": "EIA petroleum products", "data": {}}
    try:
        url = (
            "https://api.eia.gov/v2/petroleum/pri/spt/data/"
            "?api_key=DEMO_KEY&frequency=weekly"
            "&data[0]=value"
            "&facets[series][]=EER_EPD2F_PF4_RGC_DPG"
            "&facets[series][]=EER_EPNO_PF4_RGC_DPG"
            "&sort[0][column]=period&sort[0][direction]=desc&length=2"
        )
        r = _get(url)
        rows = r.json().get("response", {}).get("data", [])
        for row in rows:
            s, val, period = row.get("series"), row.get("value"), row.get("period")
            if "EER_EPD2F" in s:
                result["data"]["us_diesel_gal"] = {"price": val, "period": period}
            elif "EER_EPNO" in s:
                result["data"]["heating_oil_gal"] = {"price": val, "period": period}
    except Exception as e:
        result["error"] = str(e)
    return result


def scrape_freightos_fbi() -> dict:
    result = {"source": "Freightos FBX", "data": {}, "headlines": []}
    try:
        r = _get("https://fbx.freightos.com/")
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("[class*='index'], [class*='route'], [class*='rate']"):
            text = card.get_text(" ", strip=True)
            if text and len(text) < 200:
                result["headlines"].append(text)
        full_text = soup.get_text(" ")
        matches = re.findall(r"(?:FBX|index)[^\d]*(\d{1,4}(?:,\d{3})*(?:\.\d+)?)", full_text, re.I)
        result["data"]["extracted_rates"] = matches[:6]
    except Exception as e:
        result["error"] = str(e)
    return result


def scrape_baltic_via_hellenic() -> dict:
    result = {"source": "HellenicShipping/Baltic TD3C", "data": {}, "articles": []}
    try:
        r = _get("https://www.hellenicshippingnews.com/tag/vlcc/")
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("article h2 a, article h3 a")[:10]:
            title = a.get_text(strip=True)
            href  = a.get("href", "")
            result["articles"].append({"title": title, "url": href})
            ws   = re.search(r"WS\s*(\d{2,3})", title, re.I)
            rate = re.search(r"\$([\d,]+)k?\s*(?:per day|/day)?", title, re.I)
            if ws:
                result["data"]["td3c_ws"] = ws.group(1)
            if rate:
                result["data"]["td3c_usd_day"] = rate.group(1)
        if result["articles"]:
            r2 = _get(result["articles"][0]["url"])
            soup2 = BeautifulSoup(r2.text, "lxml")
            paras = [p.get_text(" ", strip=True) for p in soup2.select("p")]
            result["data"]["article_extract"] = [p for p in paras if "TD3C" in p or "VLCC" in p][:3]
    except Exception as e:
        result["error"] = str(e)
    return result


def scrape_alphaliner_sentiment() -> dict:
    result = {"source": "Alphaliner", "headlines": []}
    try:
        r = _get("https://alphaliner.axsmarine.com/PublicAlphaliner/")
        soup = BeautifulSoup(r.text, "lxml")
        for el in soup.select("h2, h3, .news-title, li")[:20]:
            text = el.get_text(strip=True)
            if len(text) > 20:
                result["headlines"].append(text)
    except Exception as e:
        result["error"] = str(e)
    return result


def scrape_singapore_inventory() -> dict:
    result = {"source": "IE Singapore", "data": {}}
    try:
        r = _get("https://www.iesingapore.gov.sg/energy-files/petroleum-data")
        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text(" ")
        m = re.search(r"middle\s+distillates?[^\d]*(\d+(?:\.\d+)?)\s*(?:million\s+barrels?|M\s*bbl)", text, re.I)
        if m:
            result["data"]["middle_distillates_mbbl"] = m.group(1)
        links = [a.get("href") for a in soup.select("a[href*='weekly'], a[href*='.pdf']")]
        result["data"]["report_links"] = links[:3]
    except Exception as e:
        result["error"] = str(e)
    return result


def scrape_all_prices() -> dict:
    print("  [prices] EIA crude...")
    eia = scrape_eia_prices()
    print("  [prices] EIA products...")
    eia_prod = scrape_eia_products()
    print("  [prices] Freightos FBX...")
    fbx = scrape_freightos_fbi()
    print("  [prices] Baltic/Hellenic TD3C...")
    baltic = scrape_baltic_via_hellenic()
    print("  [prices] Alphaliner...")
    alpha = scrape_alphaliner_sentiment()
    print("  [prices] Singapore inventory...")
    sg = scrape_singapore_inventory()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eia_crude": eia,
        "eia_products": eia_prod,
        "freightos_fbx": fbx,
        "baltic_td3c": baltic,
        "alphaliner": alpha,
        "singapore_inventory": sg,
    }


if __name__ == "__main__":
    print(json.dumps(scrape_all_prices(), indent=2, ensure_ascii=False))
