"""
Price scraper (v2)

Brent / WTI 只信任「可驗證來源」，不可由 AI 推估：
  1) Stooq 期貨報價 CSV（Brent=CB.F, WTI=CL.F）  -> stooq_futures
  2) EIA 日現貨（Brent=RBRTE, WTI=RWTC，約落後 1-3 個交易日） -> spot_daily
其餘（EIA 週資料、成品油、運費、庫存）僅作為 AI 分析的背景資料。

可選：在 GitHub Secrets 新增 EIA_API_KEY（免費申請），否則使用 DEMO_KEY。
"""
import csv
import io
import json
import os
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}
T = httpx.Timeout(25.0)
EIA_KEY = os.environ.get("EIA_API_KEY") or "DEMO_KEY"


def _get(url, **kw):
    with httpx.Client(headers=HEADERS, timeout=T, follow_redirects=True) as c:
        return c.get(url, **kw)


# ───────────────────────── 可驗證價格來源 ─────────────────────────
def _stooq_quote(symbol: str):
    """Stooq 單一報價 CSV。回傳 {price, period, time, symbol} 或 None。"""
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    r = _get(url)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows:
        return None
    row = rows[0]
    close = (row.get("Close") or "").strip()
    if not close or close.upper() == "N/D":
        return None
    return {
        "price": float(close),
        "period": (row.get("Date") or "").strip(),
        "time": (row.get("Time") or "").strip(),
        "symbol": (row.get("Symbol") or symbol).strip(),
    }


def scrape_stooq_futures() -> dict:
    """Brent / WTI 期貨最新價（較即時；可能被封鎖，失敗時會回退到 EIA）。"""
    result = {"source": "Stooq futures (CB.F / CL.F)", "data": {}}
    for key, sym in (("brent", "cb.f"), ("wti", "cl.f")):
        try:
            q = _stooq_quote(sym)
            if q:
                result["data"][key] = q
        except Exception as e:
            result.setdefault("errors", []).append(f"{key}: {e}")
    if not result["data"]:
        result["error"] = "; ".join(result.get("errors", ["no data"]))
    return result


def scrape_spot_daily() -> dict:
    """EIA 日現貨價 Brent(RBRTE) / WTI(RWTC)，官方資料，約落後 1-3 個交易日。"""
    result = {"source": "EIA daily spot", "data": {}}
    try:
        url = (
            "https://api.eia.gov/v2/petroleum/pri/spt/data/"
            f"?api_key={EIA_KEY}&frequency=daily&data[0]=value"
            "&facets[series][]=RBRTE&facets[series][]=RWTC"
            "&sort[0][column]=period&sort[0][direction]=desc&length=10"
        )
        rows = _get(url).json().get("response", {}).get("data", [])
        for row in rows:
            s = row.get("series")
            key = "brent" if s == "RBRTE" else "wti" if s == "RWTC" else None
            if key and key not in result["data"] and row.get("value") is not None:
                result["data"][key] = {
                    "price": float(row["value"]),
                    "period": row.get("period"),
                }
        if not result["data"]:
            result["error"] = "EIA returned no rows"
    except Exception as e:
        result["error"] = str(e)
    return result


# ───────────────────────── 背景資料（不作為價格依據） ─────────────────────────
def scrape_eia_prices() -> dict:
    """EIA 週資料（落後約 1 週，僅供參考）。"""
    result = {"source": "EIA weekly (stale, reference only)", "data": {}}
    try:
        url = (
            "https://api.eia.gov/v2/petroleum/pri/spt/data/"
            f"?api_key={EIA_KEY}&frequency=weekly"
            "&data[0]=value"
            "&facets[series][]=RBRTE"
            "&facets[series][]=RWTC"
            "&sort[0][column]=period&sort[0][direction]=desc&length=6"
        )
        rows = _get(url).json().get("response", {}).get("data", [])
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
            f"?api_key={EIA_KEY}&frequency=weekly"
            "&data[0]=value"
            "&facets[series][]=EER_EPD2F_PF4_RGC_DPG"
            "&facets[series][]=EER_EPNO_PF4_RGC_DPG"
            "&sort[0][column]=period&sort[0][direction]=desc&length=2"
        )
        rows = _get(url).json().get("response", {}).get("data", [])
        for row in rows:
            s, val, period = row.get("series"), row.get("value"), row.get("period")
            if "EER_EPD2F" in (s or ""):
                result["data"]["us_diesel_gal"] = {"price": val, "period": period}
            elif "EER_EPNO" in (s or ""):
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
            href = a.get("href", "")
            result["articles"].append({"title": title, "url": href})
            ws = re.search(r"WS\s*(\d{2,3})", title, re.I)
            rate = re.search(r"\$([\d,]+)k?\s*(?:per day|/day)?", title, re.I)
            if ws and "td3c_ws" not in result["data"]:
                result["data"]["td3c_ws"] = ws.group(1)
            if rate and "td3c_usd_day" not in result["data"]:
                result["data"]["td3c_usd_day"] = rate.group(1)
        if result["articles"]:
            r2 = _get(result["articles"][0]["url"])
            soup2 = BeautifulSoup(r2.text, "lxml")
            paras = [p.get_text(" ", strip=True) for p in soup2.select("p")]
            result["data"]["article_extract"] = [
                p for p in paras if "TD3C" in p or "VLCC" in p
            ][:3]
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
        m = re.search(
            r"middle\s+distillates?[^\d]*(\d+(?:\.\d+)?)\s*(?:million\s+barrels?|M\s*bbl)",
            text, re.I,
        )
        if m:
            result["data"]["middle_distillates_mbbl"] = m.group(1)
        links = [a.get("href") for a in soup.select("a[href*='weekly'], a[href*='.pdf']")]
        result["data"]["report_links"] = links[:3]
    except Exception as e:
        result["error"] = str(e)
    return result


def scrape_all_prices() -> dict:
    print("  [prices] Stooq futures (Brent/WTI)...")
    stooq = scrape_stooq_futures()
    print("  [prices] EIA daily spot (Brent/WTI)...")
    spot = scrape_spot_daily()
    print("  [prices] EIA weekly...")
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
        "stooq_futures": stooq,      # 可驗證：期貨
        "spot_daily": spot,          # 可驗證：EIA 日現貨
        "eia_crude": eia,
        "eia_products": eia_prod,
        "freightos_fbx": fbx,
        "baltic_td3c": baltic,
        "alphaliner": alpha,
        "singapore_inventory": sg,
    }


if __name__ == "__main__":
    print(json.dumps(scrape_all_prices(), indent=2, ensure_ascii=False))
