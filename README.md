# 🛢 Oil Market Daily Tracker

每天台灣時間 06:00 自動抓取原油市場數據，透過 Claude AI 分析，產出 Markdown 報告並更新 Web Dashboard。

## 快速開始（10 分鐘設定）

### Step 1 — Fork 這個 Repo

GitHub 右上角 → Fork → 取名（例如 `oil-tracker`）

### Step 2 — 設定 Secrets

進入你的 repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 名稱 | 說明 |
|---|---|
| `ANTHROPIC_API_KEY` | 從 console.anthropic.com 取得 |

### Step 3 — 啟用 GitHub Pages

**Settings → Pages → Source → Deploy from a branch**
- Branch: `main`
- Folder: `/docs`

儲存後等 1–2 分鐘，你的網站網址會是：
`https://<你的帳號>.github.io/<repo名稱>/`

### Step 4 — 手動觸發第一次

**Actions → Oil Market Daily Report → Run workflow**

看到綠色 ✓ 代表成功，之後每天 06:00 (台灣) 自動執行。

---

## 專案結構

```
.github/workflows/daily_report.yml   # 排程觸發
scrapers/
  prices.py          # EIA + Freightos + Baltic (Hellenic) + Alphaliner
  geopolitics.py     # Reuters + CENTCOM + OFAC + Tasnim + Aramco
  southeast_asia.py  # Philippines DOE + Indonesia ESDM + MPOB CPO
analysis/
  analyzer.py        # Claude API 分析核心
  dashboard.py       # 靜態網站生成器
output/              # 每日報告存檔 (git commit)
docs/
  index.html         # GitHub Pages 網站（自動生成）
main.py              # 執行入口
requirements.txt
```

## 數據來源（全部免費）

| 類別 | 來源 |
|---|---|
| Brent / WTI | EIA Open Data API（DEMO_KEY，無需註冊）|
| 運費 TD3C | Freightos FBX + Hellenic Shipping News（Baltic 免費轉載）|
| 航運情緒 | Alphaliner 公開頁面 |
| 地緣政治 | Reuters Energy + CENTCOM 官網 |
| 制裁 | OFAC Treasury.gov |
| 伊朗官方 | Tasnim News Agency |
| 煉廠 | Aramco Newsroom |
| 菲律賓 | DOE Philippines |
| 印尼 | ESDM + Pertamina |
| 馬來西亞 CPO | Bursa Malaysia + MPOB |

## 費用估計

| 項目 | 費用 |
|---|---|
| GitHub Actions | 免費（2,000 min/月，每次約 5–8 分鐘）|
| Claude API | ~$0.05–0.15 / 天（claude-sonnet-4-6）|
| 月合計 | **~NT$50–150 / 月** |
