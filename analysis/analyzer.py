import json, os, re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

SYSTEM_PROMPT = """你是一位專業的原油市場分析師，每天06:00（台灣時間）自動產出報告。

報告格式嚴格遵照以下結構：

# 原油市場深度分析報告 — {日期}（第N輪查核）
> 台灣時間 06:00 更新 | P&I 停保第N天 | {事件}

### 一、價格軌跡
表格必須包含 Brent 和 WTI 的當日價格（USD/bbl）

### 二、P&I 四階段

### 三、柴油/煉油
表格必須包含「柴油裂解差」欄位，格式為數字 USD/bbl，例如：$25.50

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

規則：四個情境①②③④加總=100%，數據缺失標記「數據待確認」。"""


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

請產出今日完整Markdown報告。嚴格遵守格式規定，特別注意：
1. 機率表格必須用①②③④符號
2. E[P]必須寫成「E[P] 2-3週：~$XX.XX」格式
3. 柴油裂解差必須是合理數值（$15-$80之間）"""


def extract_kv(report_md: str, scraped: dict) -> dict:
    def fp(pattern, flags=0):
        m = re.search(pattern, report_md, flags)
        return m.group(1) if m else None

    # Brent — 從表格抓，格式 | Brent 原油 | **89.73** |
    brent = fp(r"\|\s*\*?\*?Brent[^|]*\|\s*\*?\*?\$?\s*(8\d\.\d+|9\d\.\d+|7\d\.\d+)")
    if not brent:
        brent = fp(r"Brent[^\d]{0,5}(8\d\.\d{2}|9\d\.\d{2}|7\d\.\d{2})")

    # WTI
    wti = fp(r"\|\s*\*?\*?WTI[^|]*\|\s*\*?\*?\$?\s*(7\d\.\d+|8\d\.\d+|9\d\.\d+)")
    if not wti:
        wti = fp(r"WTI[^\d]{0,5}(7\d\.\d{2}|8\d\.\d{2}|9\d\.\d{2})")

    # Diesel crack — 合理範圍 $15-$80，避免抓到庫存數字
    crack = fp(r"柴油裂解差[^|$\d]{0,20}\$?\s*([2-7]\d\.\d{1,2})")
    if not crack:
        crack = fp(r"Crack[^|$\d]{0,20}\$?\s*([2-7]\d\.\d{1,2})", re.I)

    # TD3C WS rate
    td3c = fp(r"TD3C[^W\d]{0,15}WS\s*(\d{2,3})")
    if not td3c:
        td3c = fp(r"WS\s*(\d{2,3})")

    # Scenario probabilities ①②③④ — from table row
    s1 = fp(r"①[^|\d%]{0,10}(\d+)\s*%")
    s2 = fp(r"②[^|\d%]{0,10}(\d+)\s*%")
    s3 = fp(r"③[^|\d%]{0,10}(\d+)\s*%")
    s4 = fp(r"④[^|\d%]{0,10}(\d+)\s*%")

    # E[P] — must capture the price number after ~$
    ep = fp(r"E\[P\]\s*2-3週[^\d~$]{0,5}~?\s*\$\s*(\d{2,3}\.\d{1,2})")
    if not ep:
        ep = fp(r"E\[P\][^\d]{0,20}(\d{2,3}\.\d{2})")

    result = {
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
    print(f"  [extract] brent={brent} wti={wti} crack={crack} "
          f"s1={s1}% s2={s2}% s3={s3}% s4={s4}% ep={ep}")
    return result


def run_analysis(scraped: dict) -> tuple:
    prev_report = load_prev_report()
    prev_json   = load_prev_json()
    prompt      = build_prompt(scraped, prev_report, prev_json)
    print("  [AI] Calling Gemini API...")
    report_md   = _call_gemini(prompt)
    return report_md, extract_kv(report_md, scraped)
