"""
Geopolitics scraper
Sources: Reuters, CENTCOM, OFAC, Hellenic Shipping, Tasnim, Aramco
"""
import httpx, json, re
from bs4 import BeautifulSoup
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}
T = httpx.Timeout(25.0)
KW_MIL = ["iran","irgc","hormuz","strait","mine","larak","kharg","missile","drone","centcom","sanctions","bessent","ofac","houthi","jazan","aramco","nuclear","npt"]
KW_SHIP = ["p&i","war risk","intertanko","bimco","ics","tanker","vlcc","td3","freight","insurance"]

def _get(url):
    with httpx.Client(headers=HEADERS, timeout=T, follow_redirects=True) as c:
        return c.get(url)

def _filter(items, keys):
    out = []
    for it in items:
        txt = (it.get("title","") + " " + it.get("summary","")).lower()
        if any(k in txt for k in keys):
            out.append(it)
    return out

def scrape_reuters() -> dict:
    result = {"source": "Reuters", "headlines": [], "filtered": []}
    try:
        for url in ["https://www.reuters.com/business/energy/","https://www.reuters.com/world/middle-east/"]:
            r = _get(url)
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select("a[data-testid='Heading']")[:20]:
                title = a.get_text(strip=True)
                href  = a.get("href","")
                if href and not href.startswith("http"):
                    href = "https://www.reuters.com" + href
                result["headlines"].append({"title": title, "url": href})
        result["filtered"] = _filter(result["headlines"], KW_MIL)
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_centcom() -> dict:
    result = {"source": "CENTCOM", "releases": [], "filtered": []}
    try:
        r = _get("https://www.centcom.mil/MEDIA/PRESS-RELEASES/")
        soup = BeautifulSoup(r.text, "lxml")
        for item in soup.select(".alist-item, article")[:15]:
            title_el = item.select_one("h2,h3,h4,a")
            date_el  = item.select_one("time,.date")
            if title_el:
                result["releases"].append({
                    "title": title_el.get_text(strip=True),
                    "date":  date_el.get_text(strip=True) if date_el else "",
                })
        result["filtered"] = _filter(result["releases"], KW_MIL)
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_ofac() -> dict:
    result = {"source": "OFAC/Treasury", "actions": [], "filtered": []}
    try:
        r = _get("https://ofac.treasury.gov/recent-actions")
        soup = BeautifulSoup(r.text, "lxml")
        for row in soup.select("table tr, .views-row, li")[:25]:
            text = row.get_text(" ", strip=True)
            if len(text) > 10:
                result["actions"].append(text[:300])
        result["filtered"] = [a for a in result["actions"]
                               if any(k in a.lower() for k in ["iran","energy","oil","ship","bank","misr"])]
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_hellenic_shipping() -> dict:
    result = {"source": "HellenicShipping", "headlines": [], "filtered": []}
    try:
        for url in ["https://www.hellenicshippingnews.com/category/shipping-news/tanker-shipping/",
                    "https://www.hellenicshippingnews.com/category/insurance/"]:
            r = _get(url)
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select("article h2 a, article h3 a")[:12]:
                result["headlines"].append({"title": a.get_text(strip=True), "url": a.get("href","")})
        result["filtered"] = _filter(result["headlines"], KW_MIL + KW_SHIP)
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_tasnim() -> dict:
    result = {"source": "Tasnim (Iran)", "headlines": [], "filtered": []}
    try:
        r = _get("https://www.tasnimnews.com/en/news/world")
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("h2 a, h3 a, .story-title a")[:20]:
            title = a.get_text(strip=True)
            href  = a.get("href","")
            if href and not href.startswith("http"):
                href = "https://www.tasnimnews.com" + href
            if title:
                result["headlines"].append({"title": title, "url": href})
        result["filtered"] = _filter(result["headlines"], KW_MIL)
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_aramco() -> dict:
    result = {"source": "Aramco", "headlines": [], "filtered": []}
    try:
        r = _get("https://www.aramco.com/en/news-media/news")
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("h2 a, h3 a, .article-title a")[:15]:
            title = a.get_text(strip=True)
            if title:
                result["headlines"].append({"title": title})
        result["filtered"] = [h for h in result["headlines"]
                               if any(k in h["title"].lower() for k in ["jazan","refinery","production","restart"])]
    except Exception as e:
        result["error"] = str(e)
    return result

def scrape_all_geopolitics() -> dict:
    print("  [geo] Reuters...")
    r = scrape_reuters()
    print("  [geo] CENTCOM...")
    c = scrape_centcom()
    print("  [geo] OFAC...")
    o = scrape_ofac()
    print("  [geo] Hellenic Shipping...")
    h = scrape_hellenic_shipping()
    print("  [geo] Tasnim...")
    t = scrape_tasnim()
    print("  [geo] Aramco...")
    a = scrape_aramco()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reuters": r, "centcom": c, "ofac": o,
        "shipping": h, "iran_official": t, "aramco": a,
    }

if __name__ == "__main__":
    print(json.dumps(scrape_all_geopolitics(), indent=2, ensure_ascii=False))
