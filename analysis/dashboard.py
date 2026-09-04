"""
Dashboard generator — 把每日 JSON + Markdown 轉成 GitHub Pages 靜態網站
輸出到 docs/ 目錄（GitHub Pages 設定 source = docs/）
"""
import json, re, shutil
from datetime import datetime, timezone
from pathlib import Path

DOCS_DIR = Path("docs")
OUTPUT_DIR = Path("output")
DOCS_DIR.mkdir(exist_ok=True)


def load_history(n=30) -> list[dict]:
    """Load last N days of structured JSON."""
    files = sorted(OUTPUT_DIR.glob("data_*.json"), reverse=True)[:n]
    history = []
    for f in files:
        try:
            history.append(json.loads(f.read_text("utf-8")))
        except Exception:
            pass
    return list(reversed(history))  # oldest first for charts


def load_latest_report() -> str:
    reports = sorted(OUTPUT_DIR.glob("report_*.md"), reverse=True)
    return reports[0].read_text("utf-8") if reports else "報告生成中..."


def md_to_html_basic(md: str) -> str:
    """Very lightweight Markdown → HTML (tables, headers, bold, code)."""
    lines = md.split("\n")
    out = []
    in_table = False
    in_code  = False

    for line in lines:
        # Code block
        if line.startswith("```"):
            if not in_code:
                out.append('<pre class="code-block"><code>')
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            out.append(line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))
            continue

        # Table row
        if line.startswith("|"):
            if not in_table:
                out.append('<div class="table-wrap"><table>')
                in_table = True
            cells = [c.strip() for c in line.split("|")[1:-1]]
            is_sep = all(re.match(r"^[-:]+$", c.replace(" ","")) for c in cells if c)
            if is_sep:
                continue
            tag = "th" if out and "<th>" not in "".join(out[-3:]) and not any("<td>" in x for x in out[-5:]) else "td"
            row = "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue
        else:
            if in_table:
                out.append("</table></div>")
                in_table = False

        # Headers
        if line.startswith("# "):
            out.append(f'<h1>{_inline(line[2:])}</h1>')
        elif line.startswith("## "):
            out.append(f'<h2>{_inline(line[3:])}</h2>')
        elif line.startswith("### "):
            out.append(f'<h3>{_inline(line[4:])}</h3>')
        elif line.startswith("> "):
            out.append(f'<blockquote>{_inline(line[2:])}</blockquote>')
        elif line.startswith("---"):
            out.append("<hr>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{_inline(line)}</p>")

    if in_table:
        out.append("</table></div>")
    return "\n".join(out)


def _inline(text: str) -> str:
    """Inline markdown: bold, italic, code, emoji colours."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`",        r"<code>\1</code>",     text)
    # Colour emoji
    text = text.replace("🔴", '<span class="tag-red">🔴</span>')
    text = text.replace("🟢", '<span class="tag-green">🟢</span>')
    text = text.replace("🟡", '<span class="tag-amber">🟡</span>')
    text = text.replace("⚡", '<span class="tag-flash">⚡</span>')
    text = text.replace("⚠️", '<span class="tag-warn">⚠️</span>')
    return text


def build_chart_data(history: list[dict]) -> str:
    labels = [d.get("date","") for d in history]
    brent  = [d.get("brent") for d in history]
    wti    = [d.get("wti")   for d in history]
    s1 = [d.get("s1_pct") for d in history]
    s3 = [d.get("s3_pct") for d in history]
    s4 = [d.get("s4_pct") for d in history]
    return f"""
const LABELS = {json.dumps(labels)};
const BRENT  = {json.dumps(brent)};
const WTI    = {json.dumps(wti)};
const S1     = {json.dumps(s1)};
const S3     = {json.dumps(s3)};
const S4     = {json.dumps(s4)};
"""


def build_kpi_cards(latest: dict) -> str:
    def kpi(label, value, sub="", cls=""):
        return f'<div class="kpi {cls}"><div class="kpi-label">{label}</div><div class="kpi-value">{value or "—"}</div><div class="kpi-sub">{sub}</div></div>'

    brent = f'${latest.get("brent","—")}' if latest.get("brent") else "—"
    wti   = f'${latest.get("wti","—")}'   if latest.get("wti")   else "—"
    ep    = f'~${latest.get("expected_price","—")}' if latest.get("expected_price") else "—"
    crack = f'${latest.get("diesel_crack","—")}' if latest.get("diesel_crack") else "—"
    ws    = f'WS{latest.get("td3c_ws","—")}' if latest.get("td3c_ws") else "—"
    s3    = f'{latest.get("s3_pct","—")}%' if latest.get("s3_pct") else "—"

    return f"""
{kpi("Brent", brent, "USD/bbl", "kpi-blue")}
{kpi("WTI",   wti,   "USD/bbl", "kpi-blue")}
{kpi("E[P] 2–3週", ep, "期望價格")}
{kpi("柴油裂解", crack, "USD/bbl")}
{kpi("TD3C", ws, "VLCC 運費")}
{kpi("③ 升級推升", s3, "最高機率情境", "kpi-amber")}
"""


def generate_html(report_md: str, history: list[dict]) -> str:
    latest      = history[-1] if history else {}
    report_html = md_to_html_basic(report_md)
    chart_data  = build_chart_data(history)
    kpi_cards   = build_kpi_cards(latest)
    today_str   = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>原油市場每日追蹤</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
:root {{
  --bg: #0f0f0e; --surface: #1a1a19; --border: #2c2c2a;
  --text: #e8e6e0; --muted: #898781; --blue: #3b82f6;
  --red: #ef4444; --green: #22c55e; --amber: #f59e0b;
  --purple: #a78bfa; --font: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; }}

.topbar {{ background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; }}
.topbar h1 {{ font-size: 16px; font-weight: 500; }}
.topbar .ts {{ font-size: 12px; color: var(--muted); }}
.badge-live {{ background: rgba(239,68,68,.15); color: var(--red);
  font-size: 11px; padding: 2px 10px; border-radius: 99px; border: 1px solid rgba(239,68,68,.3); }}

.layout {{ display: grid; grid-template-columns: 320px 1fr; height: calc(100vh - 49px); }}
.sidebar {{ background: var(--surface); border-right: 1px solid var(--border);
  overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }}
.main {{ overflow-y: auto; padding: 20px 28px; }}

/* KPI */
.kpi-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.kpi {{ background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px; }}
.kpi-blue {{ border-color: rgba(59,130,246,.3); }}
.kpi-amber {{ border-color: rgba(245,158,11,.3); }}
.kpi-label {{ font-size: 11px; color: var(--muted); margin-bottom: 4px; }}
.kpi-value {{ font-size: 20px; font-weight: 600; color: var(--text); }}
.kpi-sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}

/* Charts */
.chart-card {{ background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }}
.chart-title {{ font-size: 12px; color: var(--muted); margin-bottom: 10px; text-transform: uppercase; letter-spacing: .05em; }}
canvas {{ max-height: 130px; }}

/* Prob bars */
.prob-section {{ background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }}
.prob-title {{ font-size: 12px; color: var(--muted); margin-bottom: 10px; text-transform: uppercase; letter-spacing: .05em; }}
.prob-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 12px; }}
.prob-label {{ flex: 0 0 90px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.prob-bar-bg {{ flex: 1; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }}
.prob-fill {{ height: 100%; border-radius: 3px; }}
.prob-pct {{ flex: 0 0 32px; text-align: right; font-weight: 500; }}

/* Nav tabs */
.tabs {{ display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 0; }}
.tab {{ padding: 8px 16px; font-size: 13px; cursor: pointer; color: var(--muted);
  border-bottom: 2px solid transparent; margin-bottom: -1px; background: none; border-top: none; border-left: none; border-right: none; }}
.tab.active {{ color: var(--text); border-bottom-color: var(--blue); }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}

/* Report HTML */
.report-body h1 {{ font-size: 18px; font-weight: 600; margin: 16px 0 6px; color: var(--text); }}
.report-body h2 {{ font-size: 15px; font-weight: 500; margin: 20px 0 8px; color: var(--text);
  padding-left: 10px; border-left: 3px solid var(--blue); }}
.report-body h3 {{ font-size: 13px; font-weight: 500; margin: 14px 0 6px; color: var(--muted); }}
.report-body p {{ line-height: 1.6; margin-bottom: 6px; color: var(--text); }}
.report-body blockquote {{ border-left: 3px solid var(--amber); padding: 8px 12px;
  background: rgba(245,158,11,.05); border-radius: 0 6px 6px 0; margin: 8px 0; font-size: 13px; }}
.report-body hr {{ border: none; border-top: 1px solid var(--border); margin: 16px 0; }}
.report-body br {{ display: none; }}
.report-body .table-wrap {{ overflow-x: auto; margin: 10px 0; }}
.report-body table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.report-body th {{ background: var(--surface); color: var(--muted); font-weight: 400;
  padding: 7px 10px; border: 1px solid var(--border); text-align: left; white-space: nowrap; }}
.report-body td {{ padding: 7px 10px; border: 1px solid var(--border); color: var(--text); }}
.report-body tr:nth-child(even) td {{ background: rgba(255,255,255,.02); }}
.report-body strong {{ color: var(--text); font-weight: 600; }}
.report-body code {{ background: var(--border); padding: 1px 5px; border-radius: 4px; font-family: monospace; font-size: 12px; }}
.report-body .code-block {{ background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px; overflow-x: auto; margin: 8px 0; font-size: 12px; font-family: monospace; }}
.tag-red {{ color: var(--red); }}
.tag-green {{ color: var(--green); }}
.tag-amber {{ color: var(--amber); }}
.tag-flash {{ color: var(--amber); }}
.tag-warn {{ color: var(--amber); }}

/* History table */
.history-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.history-table th {{ background: var(--surface); color: var(--muted); font-weight: 400;
  padding: 8px 12px; border-bottom: 1px solid var(--border); text-align: left; }}
.history-table td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
.history-table tr:hover td {{ background: rgba(255,255,255,.03); }}
.up {{ color: var(--red); }} .dn {{ color: var(--green); }} .nt {{ color: var(--muted); }}

@media (max-width: 768px) {{
  .layout {{ grid-template-columns: 1fr; height: auto; }}
  .sidebar {{ border-right: none; border-bottom: 1px solid var(--border); }}
}}
</style>
</head>
<body>

<div class="topbar">
  <h1>🛢 原油市場每日追蹤</h1>
  <div style="display:flex;align-items:center;gap:12px;">
    <span class="ts">更新：{today_str}</span>
    <span class="badge-live">● LIVE</span>
  </div>
</div>

<div class="layout">
  <!-- ── Sidebar ── -->
  <div class="sidebar">
    <div class="kpi-grid">{kpi_cards}</div>

    <div class="chart-card">
      <div class="chart-title">Brent / WTI — 近30天</div>
      <canvas id="priceChart"></canvas>
    </div>

    <div class="prob-section" id="probSection">
      <div class="prob-title">機率情境</div>
      <div class="prob-row">
        <span class="prob-label">① 實質降溫</span>
        <div class="prob-bar-bg"><div class="prob-fill" id="b1" style="background:var(--green)"></div></div>
        <span class="prob-pct" id="p1">—</span>
      </div>
      <div class="prob-row">
        <span class="prob-label">② 高檔盤整</span>
        <div class="prob-bar-bg"><div class="prob-fill" id="b2" style="background:var(--blue)"></div></div>
        <span class="prob-pct" id="p2">—</span>
      </div>
      <div class="prob-row">
        <span class="prob-label">③ 升級推升</span>
        <div class="prob-bar-bg"><div class="prob-fill" id="b3" style="background:var(--amber)"></div></div>
        <span class="prob-pct" id="p3">—</span>
      </div>
      <div class="prob-row">
        <span class="prob-label">④ 全面衝突</span>
        <div class="prob-bar-bg"><div class="prob-fill" id="b4" style="background:var(--red)"></div></div>
        <span class="prob-pct" id="p4">—</span>
      </div>
    </div>

    <div class="chart-card">
      <div class="chart-title">情境③+④機率趨勢</div>
      <canvas id="probChart"></canvas>
    </div>
  </div>

  <!-- ── Main ── -->
  <div class="main">
    <div class="tabs">
      <button class="tab active" onclick="switchTab('report',this)">📄 今日報告</button>
      <button class="tab" onclick="switchTab('history',this)">📈 歷史數據</button>
    </div>

    <div id="report" class="tab-content active">
      <div class="report-body">{report_html}</div>
    </div>

    <div id="history" class="tab-content">
      <table class="history-table">
        <thead><tr>
          <th>日期</th><th>Brent</th><th>WTI</th><th>柴油裂解</th>
          <th>TD3C</th><th>③%</th><th>④%</th><th>E[P]</th>
        </tr></thead>
        <tbody id="historyBody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
{chart_data}

// ── Price chart ──
new Chart(document.getElementById('priceChart'), {{
  type: 'line',
  data: {{
    labels: LABELS,
    datasets: [
      {{ label: 'Brent', data: BRENT, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.08)',
         borderWidth: 2, pointRadius: 2, tension: 0.3, fill: true }},
      {{ label: 'WTI',   data: WTI,   borderColor: '#a78bfa', backgroundColor: 'transparent',
         borderWidth: 1.5, pointRadius: 2, tension: 0.3, borderDash: [4,3] }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#898781', font: {{ size: 11 }} }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#898781', font: {{ size: 10 }}, maxTicksLimit: 6 }}, grid: {{ color: '#2c2c2a' }} }},
      y: {{ ticks: {{ color: '#898781', font: {{ size: 10 }}, callback: v => '$'+v }}, grid: {{ color: '#2c2c2a' }} }}
    }}
  }}
}});

// ── Scenario prob bars ──
const latest = {{ s1: S1.at(-1), s2: null, s3: S3.at(-1), s4: S4.at(-1) }};
// s2 = 100 - s1 - s3 - s4
const s2 = S1.at(-1) && S3.at(-1) && S4.at(-1)
  ? (100 - parseFloat(S1.at(-1)) - parseFloat(S3.at(-1)) - parseFloat(S4.at(-1))).toFixed(1)
  : null;
[['p1','b1',S1.at(-1)], ['p2','b2',s2], ['p3','b3',S3.at(-1)], ['p4','b4',S4.at(-1)]].forEach(([pid,bid,val]) => {{
  if (val) {{
    document.getElementById(pid).textContent = val + '%';
    document.getElementById(bid).style.width  = val + '%';
  }}
}});

// ── Prob trend chart ──
new Chart(document.getElementById('probChart'), {{
  type: 'line',
  data: {{
    labels: LABELS,
    datasets: [
      {{ label: '③ 升級推升', data: S3, borderColor: '#f59e0b', borderWidth: 2,
         pointRadius: 2, tension: 0.3, fill: false }},
      {{ label: '④ 全面衝突', data: S4, borderColor: '#ef4444', borderWidth: 1.5,
         pointRadius: 2, tension: 0.3, fill: false, borderDash: [4,3] }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#898781', font: {{ size: 11 }} }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#898781', font: {{ size: 10 }}, maxTicksLimit: 6 }}, grid: {{ color: '#2c2c2a' }} }},
      y: {{ ticks: {{ color: '#898781', font: {{ size: 10 }}, callback: v => v+'%' }}, grid: {{ color: '#2c2c2a' }} }}
    }}
  }}
}});

// ── History table ──
const histData = {json.dumps(history)};
const tbody = document.getElementById('historyBody');
[...histData].reverse().forEach(d => {{
  const tr = document.createElement('tr');
  const brent = d.brent ? '$'+d.brent : '—';
  const wti   = d.wti   ? '$'+d.wti   : '—';
  tr.innerHTML = `
    <td>${{d.date||'—'}}</td>
    <td>${{brent}}</td><td>${{wti}}</td>
    <td>${{d.diesel_crack ? '$'+d.diesel_crack : '—'}}</td>
    <td>${{d.td3c_ws ? 'WS'+d.td3c_ws : '—'}}</td>
    <td>${{d.s3_pct ? d.s3_pct+'%' : '—'}}</td>
    <td>${{d.s4_pct ? d.s4_pct+'%' : '—'}}</td>
    <td>${{d.expected_price ? '~$'+d.expected_price : '—'}}</td>`;
  tbody.appendChild(tr);
}});

// ── Tab switch ──
function switchTab(id, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body>
</html>"""


def generate_dashboard(report_md: str):
    history = load_history(30)
    html    = generate_html(report_md, history)
    out     = DOCS_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    # Copy past reports as JSON API
    api_dir = DOCS_DIR / "api"
    api_dir.mkdir(exist_ok=True)
    jsons = sorted(OUTPUT_DIR.glob("data_*.json"), reverse=True)[:30]
    combined = []
    for jf in jsons:
        try:
            combined.append(json.loads(jf.read_text("utf-8")))
        except Exception:
            pass
    (api_dir / "history.json").write_text(json.dumps(combined, ensure_ascii=False), "utf-8")
    print(f"  [dashboard] Generated → {out}")
