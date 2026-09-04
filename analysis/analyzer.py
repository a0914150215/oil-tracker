"""
AI analysis engine — Google Gemini API (免費)
申請 key: https://aistudio.google.com/app/apikey
"""
import json, os, re
import urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

GEMINI_MODEL = "gemini-3.5-flash"   # 免費tier支援
GEMINI_URL   = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

SYSTEM_PROMPT = """你是一位專業的原油市場分析師，每天 06:00（台灣時間）自動產出報告。

報告格式完全遵照以下結構（章節順序不可改變）：
1. 標題行：# 原油市場深度分析報告 — {日期}（第N輪查核）
2. 副標題：> 台灣時間 06:00 更新 | P&I 停保第N天 | {當日最重大事件}
3. ⚡ 重大事件摘要（如有新事件）
4. 一、價格軌跡（表格）
5. 二、P&I 四階段（文字圖 + 運費指標表）
6. 三、柴油/煉油（指標表 + 維修動態）
7. 四、地緣政治追蹤矩陣（完整表格，含趨勢符號）
8. 五、機率框架（情境表 + 核心數字表）
9. 六、近期事件日曆（表格）
10. 免責聲明

規則：
- 若某項數據無法抓取，標記「數據待確認」，根據前日趨勢給出合理估計
- 機率四個情境加總必須 = 100%
- 機率變化必須附上 ▲▼ 箭頭和原因說明
- 有重大新事件（軍事/制裁/觸雷）在副標題加 ⚡"""


def _call_gemini(prompt: str) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    url     = f"{GEMINI_URL}?key={api_key}"
    body    = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 8192,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    # Extract text from response
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response: {data}") from e


def load_prev_report() -> str:
    reports = sorted(OUTPUT_DIR.glob("report_*.md"), reverse=True)
    return reports[0].read_text("utf-8") if reports else "（首次生成，無前日報告）"


def load_prev_json() -> dict:
    jsons = sorted(OUTPUT_DIR.glob("data_*.json"), reverse=True)
    if jsons:
        try:
            return json.loads(jsons[0].read_text("utf-8"))
        except Exception:
            pass
    return {}


def build_prompt(scraped: dict, prev_report: str, prev_json: dict) -> str:
    today        = datetime.now(timezone.utc).strftime("%Y年%-m月%-d日")
    scraped_str  = json.dumps(scraped,   ensure_ascii=False, indent=2)[:14000]
    prev_str     = json.dumps(prev_json, ensure_ascii=False, indent=2)[:3000]
    prev_rep_str = prev_report[:4000]
    return f"""今天是 {today}（台灣時間 06:00）。

## 今日抓取原始數據
```json
{scraped_str}
```

## 前日結構化數據（比對用）
```json
{prev_str}
```

## 前日 Markdown 報告（格式與輪次延續）
```
{prev_rep_str}
```

請產出今日完整 Markdown 報告。
數據缺失時標記「數據待確認」並給合理估計範圍。
機率框架必須根據今日新事件合理更新。"""


def extract_kv(report_md: str, scraped: dict) -> dict:
    def fp(pattern):
        m = re.search(pattern, report_md)
        return m.group(1) if m else None
    return {
        "date":           datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "brent":          fp(r"Brent[^\d\$]*\$?([\d.]+)"),
        "wti":            fp(r"WTI[^\d\$]*\$?([\d.]+)"),
        "diesel_crack":   fp(r"裂解[^\d\$]*\$?([\d.]+)"),
        "td3c_ws":        fp(r"WS(\d{2,3})"),
        "s1_pct":         fp(r"① [^%\d]*([\d.]+)%"),
        "s2_pct":         fp(r"② [^%\d]*([\d.]+)%"),
        "s3_pct":         fp(r"③ [^%\d]*([\d.]+)%"),
        "s4_pct":         fp(r"④ [^%\d]*([\d.]+)%"),
        "expected_price": fp(r"E\[P\][^\d\$]*\~?\$?([\d.]+)"),
        "sources_ok":     sum(1 for v in scraped.values()
                              if isinstance(v, dict) and "error" not in v),
    }


def run_analysis(scraped: dict) -> tuple[str, dict]:
    prev_report = load_prev_report()
    prev_json   = load_prev_json()
    prompt      = build_prompt(scraped, prev_report, prev_json)
    print("  [AI] Calling Gemini API...")
    report_md   = _call_gemini(prompt)
    structured  = extract_kv(report_md, scraped)
    return report_md, structured
