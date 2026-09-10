import json, os, re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

SYSTEM_PROMPT = """你是一位專業的原油市場分析師，每天06:00（台灣時間）自動產出報告。

報告格式嚴格遵照以下結構，所有符號必須完全一致：

# 原油市場深度分析報告 — {日期}（第N輪查核）
> 台灣時間 06:00 更新 | P&I 停保第N天 | {當日最重大事件}

### 一、價格軌跡（表格，含 Brent 和 WTI 欄位）
### 二、P&I 四階段
### 三、柴油/煉油（含「柴油裂解差」欄位，單位 USD/bbl）
### 四、地緣政治追蹤矩陣（表格）
### 五、機率框架

機率框架必須使用以下固定格式，符號完全一致：
| 情境 | 機率 |
|------|------|
| ① 實質降溫 | X% |
| ② 高檔盤整 | X% |
| ③ 升級推升 | X% |
| ④ 全面衝突 | X% |

核心預測數字必須包含：
E[P] 2-3週：~$XXX

### 六、近期事件日曆
### 免責聲明

規則：
- 四個情境①②③④加總必須=100%
- 機率變化附▲▼說明
- 數據缺失標記「數據待確認」"""


def _call_gemini(prompt: str) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    url = f"{GEMINI_URL}?key={api_key}"
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body,
          headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def load_prev_report() -> str:
    reports = sorted(OUTPUT_DIR.glob("report_*.md"), reverse=True)
    return reports[0].read_text("utf-8") if reports else "（首次生成）"


def load_prev_json() -> dict:
    jsons = sorted(OUTPUT_DIR.glob("data_*.json"), reverse=True)
    if jsons:
        try: return json.loads(jsons[0].read_text("utf-8"))
        except: pass
    return {}


def build_prompt(scraped, prev_report, prev_json) -> str:
    today = datetime.now(timezone.utc).strftime("%Y年%-m月%-d日")
    return f"""今天是{today}（台灣時間06:00）。

今日抓取數據：
{json.dumps(scraped, ensure_ascii=False)[:14000]}

前日結構化數據：
{json.dumps(prev_json, ensure_ascii=False)[:3000]}

前日報告：
{prev_report[:4000]}

請產出今日完整Markdown報告。嚴格遵守格式，特別是機率框架必須使用①②③④符號。"""


def extract_kv(report_md: str, scraped: dict) -> dict:
    def fp(pattern, flags=0):
        m = re.search(pattern, report_md, flags)
        return m.group(1) if m else None

    # Brent price — look for table row with Brent
    brent = fp(r"\|\s*\*?\*?Brent[^\|]*\|\s*\*?\*?\$?([\d.]+)")
    if not brent:
        brent = fp(r"Brent[^\d\$]{0,10}\$?(8\d\.\d{1,2}|9\d\.\d{1,2}|7\d\.\d{1,2})")

    # WTI price
    wti = fp(r"\|\s*\*?\*?WTI[^\|]*\|\s*\*?\*?\$?([\d.]+)")
    if not wti:
        wti = fp(r"WTI[^\d\$]{0,10}\$?(7\d\.\d{1,2}|8\d\.\d{1,2}|9\d\.\d{1,2})")

    # Diesel crack spread — must be reasonable value ($5-$60)
    crack = fp(r"柴油裂解[差價]*[^\d\$]{0,15}\$?((?:[1-5]\d|[5-9])\.\d{1,2})")
    if not crack:
        crack = fp(r"裂解差[^\d\$]{0,10}\$?([1-5]\d\.\d{1,2})")

    # TD3C WS rate
    td3c = fp(r"TD3C[^\d]*WS\s*(\d{2,3})")
    if not td3c:
        td3c = fp(r"WS\s*(\d{2,3})")

    # Scenario probabilities ①②③④
    s1 = fp(r"①[^%\d]*([\d.]+)\s*%")
    s2 = fp(r"②[^%\d]*([\d.]+)\s*%")
    s3 = fp(r"③[^%\d]*([\d.]+)\s*%")
    s4 = fp(r"④[^%\d]*([\d.]+)\s*%")

    # Expected price E[P]
    ep = fp(r"E\[P\][^\d\$~]{0,10}~?\s*\$?([\d.]+)")

    return {
        "date":           datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "brent":          brent,
        "wti":            wti,
        "diesel_crack":   crack,
        "td3c_ws":        td3c,
        "s1_pct":         s1,
        "s2_pct":         s2,
        "s3_pct":         s3,
        "s4_pct":         s4,
        "expected_price": ep,
        "sources_ok":     sum(1 for v in scraped.values()
                              if isinstance(v, dict) and "error" not in v),
    }


def run_analysis(scraped: dict) -> tuple:
    prev_report = load_prev_report()
    prev_json   = load_prev_json()
    prompt      = build_prompt(scraped, prev_report, prev_json)
    print("  [AI] Calling Gemini API...")
    report_md   = _call_gemini(prompt)
    structured  = extract_kv(report_md, scraped)
    print(f"  [AI] Extracted: Brent={structured.get('brent')} WTI={structured.get('wti')} "
          f"S1={structured.get('s1_pct')}% S3={structured.get('s3_pct')}% EP={structured.get('expected_price')}")
    return report_md, structured
