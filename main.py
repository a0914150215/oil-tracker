"""
main.py — 每日執行入口
1. 抓取所有數據來源
2. Claude API 分析
3. 存檔 output/
4. 生成 docs/index.html (GitHub Pages)
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def main():
    ts = datetime.now(timezone.utc)
    date_str = ts.strftime("%Y-%m-%d")
    print(f"\n{'='*50}")
    print(f"  Oil Market Tracker — {date_str} (UTC)")
    print(f"{'='*50}")

    # ── 1. Scrape ──────────────────────────────────────
    print("\n[1/4] Scraping data sources...")
    from scrapers.prices       import scrape_all_prices
    from scrapers.geopolitics  import scrape_all_geopolitics
    from scrapers.southeast_asia import scrape_all_sea

    prices = scrape_all_prices()
    geo    = scrape_all_geopolitics()
    sea    = scrape_all_sea()

    scraped = {
        "date": date_str,
        "prices": prices,
        "geopolitics": geo,
        "southeast_asia": sea,
    }

    # Save raw scrape
    raw_path = OUTPUT_DIR / f"raw_{date_str}.json"
    raw_path.write_text(json.dumps(scraped, ensure_ascii=False, indent=2), "utf-8")
    print(f"  Raw data saved → {raw_path}")

    # ── 2. AI Analysis ─────────────────────────────────
    print("\n[2/4] Running AI analysis...")
    from analysis.analyzer import run_analysis
    report_md, structured = run_analysis(scraped)

    # Save report
    report_path = OUTPUT_DIR / f"report_{date_str}.md"
    report_path.write_text(report_md, "utf-8")
    data_path   = OUTPUT_DIR / f"data_{date_str}.json"
    data_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), "utf-8")
    print(f"  Report saved  → {report_path}")
    print(f"  Data saved    → {data_path}")

    # ── 3. Generate Dashboard ──────────────────────────
    print("\n[3/4] Generating dashboard...")
    from analysis.dashboard import generate_dashboard
    generate_dashboard(report_md)

    # ── 4. Done ────────────────────────────────────────
    print(f"\n[4/4] Done ✓  {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    print(f"  Brent : {structured.get('brent','—')}")
    print(f"  WTI   : {structured.get('wti','—')}")
    print(f"  E[P]  : {structured.get('expected_price','—')}")
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        raise
