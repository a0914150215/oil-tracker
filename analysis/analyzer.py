"""
AI analysis engine — Google Gemini API (free)

v2 重點：
  1) Brent / WTI 只使用 prices.py 抓到的可驗證數據（Stooq 期貨 / EIA 日現貨）
  2) 禁止 AI 自行推估價格；報告產出後再做一次價格校驗，不符就改回抓取值並加警示
  3) Gemini 503/429/500 自動重試；全部失敗時產出「降級報告」，網站與歷史圖表照常更新
  4) 修正機率 / E[P] 擷取 regex
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

TW = timezone(timedelta(hours=8))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
MAX_AGE_DAYS = 5          # 價格資料超過幾天視為過期，不採用
BANNER_MARK = "**價格校驗**"

SYSTEM_PROMPT = """你是一位專業的原油市場分析師，每天06:00（台灣時間）自動產出報告。

【最高優先規則：數據誠信】
- Brent、WTI 價格只能使用使用者訊息中「已驗證價格」區塊提供的數字，並註明日期與來源。
- 「已驗證價格」若為「無」，該價格一律寫「數據待確認」，禁止自行推估、補算或編造。
- 禁止編造「前日價格」「漲跌幅」；只有在「前日結構化數據」提供了數字時才可比較。
- 柴油裂解差、運費（TD3C）、庫存：只有抓取數據或前日數據有來源時才可引用，否則寫「數據待確認」。
- 缺資料寧可留白，不可估算。

【報告格式（嚴格遵守）】

# 原油市場深度分析報告 — {日期}（第N輪查核）
> 台灣時間 06:00 更新 | P&I 停保第N天 | {事件}

### 一、價格軌跡
表格含 Brent、WTI 當日價格（USD/bbl）、日期、來源

### 二、P&I 四階段

### 三、柴油/煉油

### 四、地緣政治追蹤矩陣

### 五、機率框架
必須包含以下精確格式的表格（符號①②③④不可改變）：

| 情境 | 機率 |
|------|------|
| ① 實質降溫 | X% |
| ② 高檔盤整 | X% |
| ③ 升級推升 | X% |
| ④ 全面衝突 | X% |

核心預測數字必須單獨一行，格式完全如下：
E[P] 2-3週：~$XXX.XX

### 六、近期事件日曆
### 免責聲明

規則：四個情境加總=100%；機率變化附▲▼與原因；機率與 E[P] 必須與「已驗證價格」一致、合理。"""


# ───────────────────────── 價格驗證 ─────────────────────────
def _fresh(period: str) -> bool:
    try:
        d = datetime.strptime((period or "")[:10], "%Y-%m-%d").date()
    except Exception:
        return False
    return 0 <= (datetime.now(timezone.utc).date() - d).days <= MAX_AGE_DAYS


def pick_verified(scraped: dict) -> dict:
    """從抓取結果挑出可驗證的 Brent/WTI。優先期貨(Stooq)，其次 EIA 日現貨。"""
    prices = scraped.get("prices", {}) if isinstance(scraped, dict) else {}
    sources = (
        ("stooq_futures", "期貨 Stooq"),
        ("spot_daily", "EIA 日現貨"),
    )
    out = {}
    for key in ("brent", "wti"):
        for name, label in sources:
            rec = (prices.get(name) or {}).get("data", {}).get(key)
            if not rec:
                continue
            try:
                price = float(rec["price"])
            except Exception:
                continue
            if _fresh(rec.get("period", "")) and 20 < price < 300:
                out[key] = {
                    "price": round(price, 2),
                    "date": rec["period"][:10],
                    "source": label,
                }
                break
    return out


def format_verified(verified: dict) -> str:
    lines = []
    for key, name in (("brent", "Brent"), ("wti", "WTI")):
        v = verified.get(key)
        if v:
            lines.append(f"{name}: {v['price']:.2f} USD/bbl（日期 {v['date']}，來源 {v['source']}）")
        else:
            lines.append(f"{name}: 無（請寫「數據待確認」，禁止估算）")
    return "\n".join(lines)


def _table_price(report_md: str, name: str):
    pat = r"\|\s*\*{0,2}" + name + r"[^|\n]*\|\s*\*{0,2}\$?\s*(\d{2,3}(?:\.\d+)?)"
    return re.search(pat, report_md)


def check_report_prices(report_md: str, verified: dict):
    """報告價格與抓取值差超過 3% → 改回抓取值並在報告頂端加警示。"""
    notes = []
    for key, name in (("brent", "Brent"), ("wti", "WTI")):
        m = _table_price(report_md, name)
        v = verified.get(key)
        if not m:
            continue
        if v:
            ai = float(m.group(1))
            if abs(ai - v["price"]) / v["price"] > 0.03:
                notes.append(
                    f"{name} AI 原稿 {ai:.2f} 與抓取數據 {v['price']:.2f}"
                    f"（{v['date']}，{v['source']}）不符，已改用抓取數據"
                )
                s, e = m.span(1)
                report_md = report_md[:s] + f"{v['price']:.2f}" + report_md[e:]
        else:
            notes.append(f"{name} 無可驗證來源，報告中的 {m.group(1)} 為 AI 估值，不可作為依據")
    if notes:
        banner = (
            f"> ⚠️ {BANNER_MARK}：" + "；".join(notes)
            + "。價差、E[P]、情境機率等衍生推論請審慎參考。\n\n"
        )
        report_md = banner + report_md
    return report_md, notes


# ───────────────────────── Gemini ─────────────────────────
def _call_gemini(prompt: str) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    url = f"{GEMINI_URL}?key={api_key}"
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }).encode("utf-8")

    last_err = None
    for attempt in range(4):                      # 最多 4 次：立即、30s、60s、90s
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected Gemini response: {str(data)[:300]}") from e
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                wait = 30 * (attempt + 1)
                print(f"  [AI] Gemini HTTP {e.code}, retry in {wait}s...")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < 3:
                wait = 30 * (attempt + 1)
                print(f"  [AI] Network error {e}, retry in {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Gemini failed: {last_err}")


# ───────────────────────── 前日資料 / Prompt ─────────────────────────
def load_prev_report() -> str:
    reports = sorted(OUTPUT_DIR.glob("report_*.md"), reverse=True)
    if not reports:
        return "（首次生成）"
    text = reports[0].read_text("utf-8")
    # 去掉上次的價格校驗警示，避免 AI 模仿
    return "\n".join(l for l in text.splitlines() if BANNER_MARK not in l)


def load_prev_json() -> dict:
    jsons = sorted(OUTPUT_DIR.glob("data_*.json"), reverse=True)
    if jsons:
        try:
            return json.loads(jsons[0].read_text("utf-8"))
        except Exception:
            pass
    return {}


def build_prompt(scraped: dict, prev_report: str, prev_json: dict, verified: dict) -> str:
    today = datetime.now(TW).strftime("%Y年%-m月%-d日")
    return f"""今天是{today}（台灣時間06:00）。

## 已驗證價格（Brent/WTI 唯一可用數字）
{format_verified(verified)}

## 今日抓取數據（部分來源可能連線失敗，失敗者請標「數據待確認」）
{json.dumps(scraped, ensure_ascii=False)[:14000]}

## 前日結構化數據
{json.dumps(prev_json, ensure_ascii=False)[:3000]}

## 前日報告（延續輪次與格式用）
{prev_report[:4000]}

請產出今日完整Markdown報告，並嚴格遵守：
1. Brent/WTI 只能用「已驗證價格」，沒有就寫「數據待確認」，不可估算。
2. 機率表格用①②③④符號，四項加總 100%。
3. E[P] 寫成「E[P] 2-3週：~$XX.XX」，且必須與已驗證價格在合理範圍內。
4. 沒有來源的柴油裂解差、運費、庫存一律寫「數據待確認」。"""


# ───────────────────────── 擷取 / 降級報告 ─────────────────────────
def _count_sources(scraped: dict):
    ok = err = 0
    for group in ("prices", "geopolitics", "southeast_asia"):
        for v in (scraped.get(group) or {}).values():
            if isinstance(v, dict) and "source" in v:
                if "error" in v:
                    err += 1
                else:
                    ok += 1
    return ok, err


def extract_kv(report_md: str, scraped: dict, verified: dict) -> dict:
    def fp(pattern, flags=0):
        m = re.search(pattern, report_md, flags)
        return m.group(1) if m else None

    def prob(sym):
        return (
            fp(r"\|\s*" + sym + r"[^|\n]*\|\s*\**\s*(\d+(?:\.\d+)?)\s*%")
            or fp(sym + r"[^\n]*?(\d+(?:\.\d+)?)\s*%")
        )

    brent = f"{verified['brent']['price']:.2f}" if "brent" in verified else None
    wti = f"{verified['wti']['price']:.2f}" if "wti" in verified else None

    # TD3C：只信抓取到的資料，退而求其次才讀報告內明確寫出的 TD3C WS 數字
    td3c = (
        ((scraped.get("prices") or {}).get("baltic_td3c") or {}).get("data", {}).get("td3c_ws")
        or fp(r"TD3C[^\n|]{0,30}WS\s*(\d{2,3})")
    )

    ep = (
        fp(r"E\[P\]\s*2-3週[^\d~$]{0,5}~?\s*\$\s*(\d{2,3}(?:\.\d{1,2})?)")
        or fp(r"E\[P\][^\n]{0,20}?\$\s*(\d{2,3}(?:\.\d{1,2})?)")
    )

    ok, err = _count_sources(scraped)
    result = {
        "date": datetime.now(TW).strftime("%Y-%m-%d"),
        "brent": brent,
        "wti": wti,
        "price_date": (verified.get("brent") or verified.get("wti") or {}).get("date"),
        "price_source": (verified.get("brent") or verified.get("wti") or {}).get("source"),
        "diesel_crack": None,       # 目前沒有可驗證來源，不從 AI 文字擷取
        "td3c_ws": td3c,
        "s1_pct": prob("①"),
        "s2_pct": prob("②"),
        "s3_pct": prob("③"),
        "s4_pct": prob("④"),
        "expected_price": ep,
        "sources_ok": ok,
        "sources_error": err,
    }
    print(
        f"  [extract] brent={brent} wti={wti} s1={result['s1_pct']}% "
        f"s2={result['s2_pct']}% s3={result['s3_pct']}% s4={result['s4_pct']}% ep={ep}"
    )
    return result


def fallback_report(verified: dict, reason: str) -> str:
    today = datetime.now(TW).strftime("%Y年%-m月%-d日")
    def row(name, key):
        v = verified.get(key)
        return (f"| **{name}** | **{v['price']:.2f}** | {v['date']} | {v['source']} |"
                if v else f"| **{name}** | 數據待確認 | — | — |")
    return (
        f"# 原油市場深度分析報告 — {today}（AI 分析暫時無法產生）\n"
        f"> 台灣時間 06:00 更新 | 僅顯示已驗證價格\n\n"
        f"> ⚠️ AI 分析服務暫時無法使用（{reason[:120]}），本日僅更新已驗證價格，"
        f"機率框架與地緣政治分析請待下次更新。\n\n"
        f"### 一、價格軌跡\n\n"
        f"| 指標油種 | 價格 (USD/bbl) | 資料日期 | 來源 |\n"
        f"|---|---|---|---|\n"
        f"{row('Brent 原油', 'brent')}\n{row('WTI 原油', 'wti')}\n\n"
        f"### 免責聲明\n\n本報告僅供參考，不構成任何投資建議。\n"
    )


def run_analysis(scraped: dict) -> tuple:
    verified = pick_verified(scraped)
    print(f"  [verified] {json.dumps(verified, ensure_ascii=False)}")

    prompt = build_prompt(scraped, load_prev_report(), load_prev_json(), verified)
    print("  [AI] Calling Gemini API...")
    try:
        report_md = _call_gemini(prompt)
        report_md, notes = check_report_prices(report_md, verified)
        for n in notes:
            print(f"  [check] {n}")
    except Exception as e:
        print(f"  [AI] Gemini failed after retries: {e}")
        report_md = fallback_report(verified, str(e))

    return report_md, extract_kv(report_md, scraped, verified)
