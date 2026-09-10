import json
import os
import re
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ============================================================
# Gemini API
# ============================================================

GEMINI_MODEL = "gemini-3.5-flash"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


# ============================================================
# System Prompt
# ============================================================

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
- 數據缺失標記「數據待確認」
- 不得自行捏造不存在的市場數據
- 若來源互相矛盾，必須標記「爭議 / DISPUTED」
- 若重大事件只有單一來源且尚未獲其他來源確認，標記「未確認 / UNVERIFIED」
- 不得將未確認事件直接描述為已確認事實
- 對價格等連續數據，如果無法取得，才可以參考前日數據，但必須標記為估計
"""


# ============================================================
# Gemini API Call
# ============================================================

def _call_gemini(prompt: str) -> str:

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. "
            "Please configure GitHub Actions Secret."
        )

    url = f"{GEMINI_URL}?key={api_key}"

    body = json.dumps({
        "system_instruction": {
            "parts": [
                {
                    "text": SYSTEM_PROMPT
                }
            ]
        },

        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],

        "generationConfig": {
            "maxOutputTokens": 8192
        }

    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(
                resp.read().decode("utf-8")
            )

    except Exception as e:

        raise RuntimeError(
            f"Gemini API request failed: {e}"
        ) from e

    try:

        return (
            data["candidates"][0]
                ["content"]
                ["parts"][0]
                ["text"]
        )

    except (KeyError, IndexError, TypeError):

        raise RuntimeError(
            f"Unexpected Gemini response: {json.dumps(data, ensure_ascii=False)[:3000]}"
        )


# ============================================================
# Load previous report
# ============================================================

def load_prev_report() -> str:

    reports = sorted(
        OUTPUT_DIR.glob("report_*.md"),
        reverse=True
    )

    if reports:
        return reports[0].read_text("utf-8")

    return "（首次生成）"


# ============================================================
# Load previous structured data
# ============================================================

def load_prev_json() -> dict:

    jsons = sorted(
        OUTPUT_DIR.glob("data_*.json"),
        reverse=True
    )

    if jsons:

        try:
            return json.loads(
                jsons[0].read_text("utf-8")
            )

        except Exception:
            pass

    return {}


# ============================================================
# Build AI Prompt
# ============================================================

def build_prompt(scraped, prev_report, prev_json) -> str:

    today = datetime.now(
        TAIPEI_TZ
    ).strftime("%Y年%-m月%-d日")

    return f"""今天是 {today}（台灣時間）。

## 今日抓取數據

```json
{json.dumps(
    scraped,
    ensure_ascii=False,
    indent=2
)[:14000]}




