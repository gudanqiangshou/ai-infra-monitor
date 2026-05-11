#!/usr/bin/env python3
# render_html.py - 生成 HTML Dashboard (ECharts)
"""
四个 Tab:
1. Capex Dashboard - 季度趋势、年度对比、指引变更
2. Token Dashboard - 月度趋势、Top10模型、中美对比
3. 投资关联 - NVDA/TSM/HBM 价格走势 vs Capex
4. 今日要闻 - 时间倒序事件列表
"""
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

OUT_HTML = Path(__file__).parent.parent / "docs" / "index.html"


def query_capex_quarterly():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT company, calendar_year, calendar_quarter, capex_billion_usd, yoy_growth
        FROM capex_quarterly
        ORDER BY calendar_year, calendar_quarter, company
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_capex_guidance():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT company, guidance_year,
               guidance_low_billion, guidance_high_billion,
               guidance_point_billion, announced_date, source
        FROM capex_guidance
        ORDER BY guidance_year, announced_date, company
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_token_monthly():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT platform, year, month, tokens_trillion, daily_avg_trillion, source
        FROM token_monthly
        ORDER BY year, month, platform
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_model_weekly():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT model_id, model_name, provider, country, week_start,
               rank, tokens_trillion
        FROM token_model_weekly
        ORDER BY week_start, rank
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_assets():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, date, close
        FROM asset_prices
        WHERE date >= ?
        ORDER BY date, ticker
    """, ((datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d"),))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_china_capex():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT company, calendar_year, calendar_quarter,
               capex_billion_cny, capex_billion_usd
        FROM china_capex_quarterly
        ORDER BY calendar_year, calendar_quarter, company
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_tsmc():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT year, month, revenue_billion_twd, revenue_billion_usd, yoy_pct, mom_pct
        FROM tsmc_monthly
        ORDER BY year, month
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_korea():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT year, month, exports_billion_usd, memory_billion_usd, yoy_pct
        FROM korea_semi_exports
        ORDER BY year, month
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_power():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT year, category, twh_per_year
        FROM power_competition
        ORDER BY year, category
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def query_recent_events(limit=50, min_severity=3):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT category, title, summary, url, source_name,
               published_at, discovered_at, severity, entities
        FROM news_events
        WHERE severity >= ?
        ORDER BY discovered_at DESC
        LIMIT ?
    """, (min_severity, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ======================================================================
# 数据加工：把SQL查询结果转成 ECharts 友好格式
# ======================================================================
COMPANY_NAMES = {"AMZN": "Amazon", "MSFT": "Microsoft", "GOOGL": "Alphabet", "META": "Meta"}
COMPANY_COLORS = {"AMZN": "#FF9900", "MSFT": "#00A4EF", "GOOGL": "#4285F4", "META": "#0866FF"}


def prep_capex_quarterly_data(rows):
    """季度Capex - 多线图"""
    quarters = sorted(set(f"{r['calendar_year']} Q{r['calendar_quarter']}" for r in rows))
    series = {}
    for company in COMPANY_NAMES:
        series[company] = []
        for q in quarters:
            y, qt = q.split(" Q")
            match = [r for r in rows if r["company"] == company
                     and r["calendar_year"] == int(y)
                     and r["calendar_quarter"] == int(qt)]
            series[company].append(match[0]["capex_billion_usd"] if match else None)
    return quarters, series


def prep_capex_annual(rows, guidance):
    """年度Capex - 堆叠柱状（含指引）"""
    years = sorted(set(r["calendar_year"] for r in rows))
    actual = {c: [] for c in COMPANY_NAMES}
    for y in years:
        for c in COMPANY_NAMES:
            total = sum(r["capex_billion_usd"] for r in rows
                        if r["company"] == c and r["calendar_year"] == y)
            actual[c].append(round(total, 1) if total > 0 else None)

    # 添加2026指引 (取最新)
    guidance_2026 = {c: None for c in COMPANY_NAMES}
    for g in guidance:
        if g["guidance_year"] == 2026:
            guidance_2026[g["company"]] = g["guidance_point_billion"]
    years_ext = list(years) + ["2026 (指引)"]
    for c in COMPANY_NAMES:
        actual[c].append(guidance_2026[c])
    return years_ext, actual


def prep_token_monthly_data(rows):
    """月度Token - 多线图（仅平台级）"""
    platforms = ["gemini", "gpt", "doubao", "qwen", "openrouter"]
    months = sorted(set(f"{r['year']}-{r['month']:02d}" for r in rows))
    series = {}
    for p in platforms:
        series[p] = []
        for m in months:
            y, mo = m.split("-")
            match = [r for r in rows if r["platform"] == p
                     and r["year"] == int(y) and r["month"] == int(mo)]
            series[p].append(match[0]["tokens_trillion"] if match else None)
    return months, series


def prep_model_ranking_latest(rows):
    """OpenRouter Top10 最新周"""
    latest_week = max((r["week_start"] for r in rows), default=None)
    if not latest_week:
        return [], []
    latest = [r for r in rows if r["week_start"] == latest_week]
    latest.sort(key=lambda x: x["rank"] or 99)
    return latest_week, latest[:10]


def prep_china_vs_us_share(rows):
    """中美模型 OpenRouter 占比"""
    weeks = sorted(set(r["week_start"] for r in rows))
    cn_data, us_data = [], []
    for w in weeks:
        week_rows = [r for r in rows if r["week_start"] == w]
        cn = sum(r["tokens_trillion"] for r in week_rows if r["country"] == "CN")
        us = sum(r["tokens_trillion"] for r in week_rows if r["country"] == "US")
        total = cn + us
        if total > 0:
            cn_data.append(round(cn / total * 100, 1))
            us_data.append(round(us / total * 100, 1))
        else:
            cn_data.append(0)
            us_data.append(0)
    return weeks, cn_data, us_data


def prep_asset_prices(rows):
    """资产价格归一化（首期=100）"""
    tickers = sorted(set(r["ticker"] for r in rows))
    dates = sorted(set(r["date"][:7] for r in rows))  # 按月聚合
    series = {}
    for t in tickers:
        ticker_rows = [r for r in rows if r["ticker"] == t]
        ticker_rows.sort(key=lambda x: x["date"])
        if not ticker_rows:
            continue
        base = ticker_rows[0]["close"]
        if not base or base == 0:
            continue
        monthly = {}
        for r in ticker_rows:
            ym = r["date"][:7]
            monthly[ym] = round(r["close"] / base * 100, 1)
        series[t] = [monthly.get(d) for d in dates]
    return dates, series


# ======================================================================
# HTML 模板
# ======================================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>AI基建投资监控 Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 0; padding: 0; background: #f5f6fa; color: #2c3e50; }
.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;
          padding: 24px 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.header h1 { margin: 0 0 8px 0; font-size: 24px; font-weight: 600; }
.header .meta { font-size: 13px; opacity: 0.9; }
.tabs { display: flex; flex-wrap: wrap; background: white; border-bottom: 1px solid #e5e8eb;
        padding: 0 32px; position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.tab { padding: 16px 24px; cursor: pointer; font-size: 14px; font-weight: 500;
       color: #64748b; border-bottom: 3px solid transparent; transition: all 0.2s; }
.tab.active { color: #667eea; border-bottom-color: #667eea; }
.tab:hover { color: #667eea; background: #f8fafc; }
.content { padding: 24px 32px; }
.tab-pane { display: none; }
.tab-pane.active { display: block; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.grid-1 { display: grid; grid-template-columns: 1fr; gap: 20px; margin-bottom: 20px; }
.card { background: white; border-radius: 12px; padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.card h3 { margin: 0 0 12px 0; font-size: 15px; font-weight: 600; color: #1e293b; }
.card .subtitle { font-size: 12px; color: #64748b; margin-bottom: 16px; }
.chart { width: 100%; height: 360px; }
.chart-tall { height: 440px; }
.event-list { list-style: none; padding: 0; margin: 0; }
.event-item { padding: 14px 0; border-bottom: 1px solid #f1f5f9; display: flex; gap: 12px; }
.event-item:last-child { border-bottom: none; }
.event-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px;
               font-weight: 600; height: fit-content; white-space: nowrap; }
.badge-capex { background: #fef3c7; color: #92400e; }
.badge-token { background: #ddd6fe; color: #5b21b6; }
.badge-investment { background: #d1fae5; color: #065f46; }
.event-content { flex: 1; }
.event-title { font-size: 14px; font-weight: 500; color: #1e293b; margin-bottom: 4px; line-height: 1.4; }
.event-title a { color: #1e293b; text-decoration: none; }
.event-title a:hover { color: #667eea; }
.event-meta { font-size: 12px; color: #64748b; }
.severity-stars { color: #f59e0b; font-size: 11px; margin-left: 4px; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }
.stat-card { background: white; padding: 16px; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.stat-value { font-size: 22px; font-weight: 700; color: #1e293b; }
.stat-label { font-size: 12px; color: #64748b; margin-top: 4px; }
.stat-delta { font-size: 12px; color: #10b981; margin-top: 2px; }
.stat-delta.down { color: #ef4444; }
@media (max-width: 900px) {
  .grid { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
</head>
<body>

<div class="header">
  <h1>📊 AI基建投资监控 Dashboard</h1>
  <div class="meta">数据更新：__UPDATED_AT__ · 数据点：__STATS__</div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('capex')">💰 Capex Dashboard</div>
  <div class="tab" onclick="showTab('china')">🇨🇳 中国云厂商</div>
  <div class="tab" onclick="showTab('token')">🚀 Token Dashboard</div>
  <div class="tab" onclick="showTab('invest')">📈 投资关联</div>
  <div class="tab" onclick="showTab('macro')">🌏 宏观信号</div>
  <div class="tab" onclick="showTab('events')">📰 今日要闻</div>
</div>

<div class="content">

<!-- ==================== Tab 1: Capex ==================== -->
<div id="tab-capex" class="tab-pane active">

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">$__CAPEX_GUIDANCE_2026__B</div>
      <div class="stat-label">2026全年指引合计</div>
      <div class="stat-delta">YoY __CAPEX_GUIDANCE_YOY__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">$__CAPEX_LATEST_Q__B</div>
      <div class="stat-label">__CAPEX_LATEST_Q_LABEL__ 单季合计</div>
      <div class="stat-delta">YoY __CAPEX_LATEST_Q_YOY__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">$__CAPEX_2025__B</div>
      <div class="stat-label">2025全年合计</div>
      <div class="stat-delta">YoY __CAPEX_2025_YOY__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">~75%</div>
      <div class="stat-label">用于AI基础设施</div>
      <div class="stat-delta">数据中心+GPU</div>
    </div>
  </div>

  <div class="grid-1">
    <div class="card">
      <h3>季度Capex趋势 (2022 Q1 - 2026 Q1)</h3>
      <div class="subtitle">单位：亿美元 | 数据来源：各公司10-Q/10-K财报</div>
      <div id="chart-quarterly" class="chart chart-tall"></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>年度Capex堆叠对比</h3>
      <div class="subtitle">含2026年最新指引</div>
      <div id="chart-annual" class="chart"></div>
    </div>
    <div class="card">
      <h3>2026 Q1 单季占比</h3>
      <div class="subtitle">四大云厂商Capex份额</div>
      <div id="chart-q1-pie" class="chart"></div>
    </div>
  </div>

  <div class="grid-1">
    <div class="card">
      <h3>2026年Capex指引修订时间线</h3>
      <div class="subtitle">每次财报会议的指引变更</div>
      <div id="chart-guidance" class="chart"></div>
    </div>
  </div>
</div>

<!-- ==================== Tab 2: 中国云厂商 ==================== -->
<div id="tab-china" class="tab-pane">
  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">¥__CN_CAPEX_2025__B</div>
      <div class="stat-label">中国四大云 2025 Capex合计</div>
      <div class="stat-delta">折合 ~$__CN_CAPEX_2025_USD__B</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">¥__CN_CAPEX_Q1__B</div>
      <div class="stat-label">2026 Q1 单季</div>
      <div class="stat-delta">YoY __CN_CAPEX_Q1_YOY__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">__BYTEDANCE_Q1__B</div>
      <div class="stat-label">字节单家 Q1 Capex</div>
      <div class="stat-delta">大幅领先</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">__CN_VS_US_RATIO__%</div>
      <div class="stat-label">中/美Capex比例</div>
      <div class="stat-delta">基建追赶</div>
    </div>
  </div>

  <div class="grid-1">
    <div class="card">
      <h3>中国四大云季度Capex趋势</h3>
      <div class="subtitle">单位：亿人民币 | 阿里/腾讯/字节/百度</div>
      <div id="chart-cn-quarterly" class="chart chart-tall"></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>年度Capex对比 (人民币 vs 美元)</h3>
      <div class="subtitle">中美云厂商规模差距</div>
      <div id="chart-cn-us-compare" class="chart"></div>
    </div>
    <div class="card">
      <h3>2025年中国云Capex占比</h3>
      <div class="subtitle">阿里/腾讯/字节/百度</div>
      <div id="chart-cn-pie" class="chart"></div>
    </div>
  </div>
</div>

<!-- ==================== Tab 3: Token ==================== -->
<div id="tab-token" class="tab-pane">

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">~__TOKEN_DAILY_TOTAL__T</div>
      <div class="stat-label">头部平台日均Token</div>
      <div class="stat-delta">__TOKEN_DAILY_PERIOD__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">__DOUBAO_DAILY__T</div>
      <div class="stat-label">豆包日均 (__DOUBAO_PERIOD__)</div>
      <div class="stat-delta">全球第3</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">__CN_SHARE__%</div>
      <div class="stat-label">中国模型 OpenRouter 份额</div>
      <div class="stat-delta">__CN_SHARE_PERIOD__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">__OR_WEEKLY__T</div>
      <div class="stat-label">OpenRouter 周总量</div>
      <div class="stat-delta">__OR_WEEKLY_PERIOD__</div>
    </div>
  </div>

  <div class="grid-1">
    <div class="card">
      <h3>主流平台月度Token消耗趋势</h3>
      <div class="subtitle">单位：万亿(T) | Gemini/GPT/豆包/通义/OpenRouter</div>
      <div id="chart-platform" class="chart chart-tall"></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>OpenRouter Top 10 模型 (最新周)</h3>
      <div class="subtitle" id="top10-subtitle">数据周</div>
      <div id="chart-top10" class="chart"></div>
    </div>
    <div class="card">
      <h3>中美模型 OpenRouter 占比演变</h3>
      <div class="subtitle">Top10内中国vs美国Token占比</div>
      <div id="chart-cn-us" class="chart"></div>
    </div>
  </div>
</div>

<!-- ==================== Tab 3: 投资关联 ==================== -->
<div id="tab-invest" class="tab-pane">

  <div class="grid-1">
    <div class="card">
      <h3>核心受益股归一化走势 (24个月)</h3>
      <div class="subtitle">起始点=100 | NVDA/TSM/AVGO/MU/ASML/VRT/CEG/VST/ANET</div>
      <div id="chart-assets" class="chart chart-tall"></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>近期股价表现 (% MoM)</h3>
      <div class="subtitle">最近1月变动</div>
      <div id="chart-mom" class="chart"></div>
    </div>
    <div class="card">
      <h3>资产分类配置</h3>
      <div class="subtitle">按AI产业链环节</div>
      <div id="chart-asset-cat" class="chart"></div>
    </div>
  </div>
</div>

<!-- ==================== Tab 5: 宏观信号 ==================== -->
<div id="tab-macro" class="tab-pane">

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">$__TSMC_LATEST__B</div>
      <div class="stat-label">TSMC 最新月营收</div>
      <div class="stat-delta">__TSMC_LATEST_PERIOD__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">__TSMC_LATEST_YOY__</div>
      <div class="stat-label">TSMC YoY</div>
      <div class="stat-delta">AI芯片代工景气度</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">$__KOREA_LATEST__B</div>
      <div class="stat-label">韩国半导体出口</div>
      <div class="stat-delta">__KOREA_LATEST_PERIOD__</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">__KOREA_LATEST_YOY__</div>
      <div class="stat-label">韩国YoY</div>
      <div class="stat-delta">HBM/存储领先指标</div>
    </div>
  </div>

  <div class="grid-1">
    <div class="card">
      <h3>TSMC月度营收 (亿美元) — AI芯片代工景气度</h3>
      <div class="subtitle">每月10日左右公布 | 数据来源：TSMC IR</div>
      <div id="chart-tsmc" class="chart"></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>韩国半导体出口</h3>
      <div class="subtitle">每月1日公布 | 来源：MOTIE</div>
      <div id="chart-korea" class="chart"></div>
    </div>
    <div class="card">
      <h3>AI数据中心 vs 加密挖矿 电力消耗</h3>
      <div class="subtitle">TWh/年 | 来源：IEA + Cambridge BTC Index</div>
      <div id="chart-power" class="chart"></div>
    </div>
  </div>
</div>

<!-- ==================== Tab 6: 今日要闻 ==================== -->
<div id="tab-events" class="tab-pane">
  <div class="card">
    <h3>近期事件 (重要性 ≥ ⭐⭐⭐)</h3>
    <div class="subtitle">按发现时间倒序 · 限50条</div>
    <ul class="event-list" id="event-list">
      __EVENT_LIST_HTML__
    </ul>
  </div>
</div>

</div>

<script>
// Tab switching
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
}

const DATA = __DATA_JSON__;

// ============== Chart 1: 季度Capex趋势 ==============
const chart1 = echarts.init(document.getElementById('chart-quarterly'));
chart1.setOption({
  tooltip: { trigger: 'axis', formatter: function(params) {
    let s = params[0].axisValue + '<br/>';
    params.forEach(p => {
      if (p.value != null) s += `<span style="display:inline-block;width:8px;height:8px;background:${p.color};border-radius:50%;margin-right:6px"></span>${p.seriesName}: $${p.value}B<br/>`;
    });
    return s;
  }},
  legend: { top: 0, data: ['Amazon', 'Microsoft', 'Alphabet', 'Meta'] },
  grid: { left: 50, right: 30, bottom: 50, top: 40 },
  xAxis: { type: 'category', data: DATA.capex_quarters,
           axisLabel: { rotate: 45, fontSize: 11 } },
  yAxis: { type: 'value', name: '亿美元', nameTextStyle: { fontSize: 11 } },
  series: [
    { name: 'Amazon', type: 'line', smooth: true, data: DATA.capex_series.AMZN,
      itemStyle: { color: '#FF9900' }, lineStyle: { width: 2 } },
    { name: 'Microsoft', type: 'line', smooth: true, data: DATA.capex_series.MSFT,
      itemStyle: { color: '#00A4EF' }, lineStyle: { width: 2 } },
    { name: 'Alphabet', type: 'line', smooth: true, data: DATA.capex_series.GOOGL,
      itemStyle: { color: '#4285F4' }, lineStyle: { width: 2 } },
    { name: 'Meta', type: 'line', smooth: true, data: DATA.capex_series.META,
      itemStyle: { color: '#0866FF' }, lineStyle: { width: 2 } },
  ]
});

// ============== Chart 2: 年度堆叠 ==============
const chart2 = echarts.init(document.getElementById('chart-annual'));
chart2.setOption({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  legend: { top: 0 },
  grid: { left: 50, right: 20, bottom: 30, top: 40 },
  xAxis: { type: 'category', data: DATA.annual_years },
  yAxis: { type: 'value', name: '亿美元' },
  series: ['AMZN', 'MSFT', 'GOOGL', 'META'].map(c => ({
    name: ({AMZN: 'Amazon', MSFT: 'Microsoft', GOOGL: 'Alphabet', META: 'Meta'})[c],
    type: 'bar', stack: 'total', data: DATA.annual_actual[c],
    itemStyle: { color: ({AMZN: '#FF9900', MSFT: '#00A4EF', GOOGL: '#4285F4', META: '#0866FF'})[c] }
  }))
});

// ============== Chart 3: Q1 2026 饼图 ==============
const chart3 = echarts.init(document.getElementById('chart-q1-pie'));
chart3.setOption({
  tooltip: { trigger: 'item', formatter: '{b}: ${c}B ({d}%)' },
  legend: { bottom: 0 },
  series: [{
    type: 'pie', radius: ['40%', '70%'],
    data: DATA.q1_2026_pie,
    label: { formatter: '{b}\n${c}B' }
  }]
});

// ============== Chart 4: 指引时间线 ==============
const chart4 = echarts.init(document.getElementById('chart-guidance'));
chart4.setOption({
  tooltip: { trigger: 'axis' },
  legend: { top: 0 },
  grid: { left: 50, right: 30, bottom: 30, top: 40 },
  xAxis: { type: 'category', data: DATA.guidance_dates },
  yAxis: { type: 'value', name: '亿美元' },
  series: ['AMZN', 'MSFT', 'GOOGL', 'META'].map(c => ({
    name: ({AMZN: 'Amazon', MSFT: 'Microsoft', GOOGL: 'Alphabet', META: 'Meta'})[c],
    type: 'line', step: 'end',
    data: DATA.guidance_series[c],
    itemStyle: { color: ({AMZN: '#FF9900', MSFT: '#00A4EF', GOOGL: '#4285F4', META: '#0866FF'})[c] },
    lineStyle: { width: 2 },
    symbol: 'circle', symbolSize: 8
  }))
});

// ============== Chart 5: 平台月度Token ==============
const chart5 = echarts.init(document.getElementById('chart-platform'));
chart5.setOption({
  tooltip: { trigger: 'axis', formatter: function(params) {
    let s = params[0].axisValue + '<br/>';
    params.forEach(p => { if (p.value != null) s += `<span style="display:inline-block;width:8px;height:8px;background:${p.color};border-radius:50%;margin-right:6px"></span>${p.seriesName}: ${p.value}T<br/>`; });
    return s;
  }},
  legend: { top: 0, data: ['Gemini (Google)', 'GPT (OpenAI)', '豆包 (字节)', '通义千问 (阿里)', 'OpenRouter'] },
  grid: { left: 60, right: 20, bottom: 50, top: 40 },
  xAxis: { type: 'category', data: DATA.token_months, axisLabel: { rotate: 45, fontSize: 11 } },
  yAxis: { type: 'value', name: '万亿T', nameTextStyle: { fontSize: 11 } },
  series: [
    { name: 'Gemini (Google)', type: 'line', smooth: true, data: DATA.token_series.gemini, itemStyle: { color: '#4285F4' } },
    { name: 'GPT (OpenAI)', type: 'line', smooth: true, data: DATA.token_series.gpt, itemStyle: { color: '#10A37F' } },
    { name: '豆包 (字节)', type: 'line', smooth: true, data: DATA.token_series.doubao, itemStyle: { color: '#FF6B6B' } },
    { name: '通义千问 (阿里)', type: 'line', smooth: true, data: DATA.token_series.qwen, itemStyle: { color: '#FF8800' } },
    { name: 'OpenRouter', type: 'line', smooth: true, data: DATA.token_series.openrouter, itemStyle: { color: '#9333EA' } },
  ]
});

// ============== Chart 6: Top 10 模型 (横向条形) ==============
const chart6 = echarts.init(document.getElementById('chart-top10'));
chart6.setOption({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
             formatter: '{b}<br/>{c}T tokens/周' },
  grid: { left: 130, right: 30, bottom: 20, top: 10 },
  xAxis: { type: 'value', name: 'T/周' },
  yAxis: { type: 'category', data: DATA.top10_names.slice().reverse(), axisLabel: { fontSize: 11 } },
  series: [{
    type: 'bar',
    data: DATA.top10_data.slice().reverse(),
    itemStyle: {
      color: function(p) { return DATA.top10_colors[DATA.top10_names.length - 1 - p.dataIndex]; }
    },
    label: { show: true, position: 'right', formatter: '{c}T' }
  }]
});
document.getElementById('top10-subtitle').textContent = '数据周: ' + DATA.top10_week;

// ============== Chart 7: 中美占比 ==============
const chart7 = echarts.init(document.getElementById('chart-cn-us'));
chart7.setOption({
  tooltip: { trigger: 'axis' },
  legend: { top: 0, data: ['中国模型', '美国模型'] },
  grid: { left: 50, right: 30, bottom: 30, top: 40 },
  xAxis: { type: 'category', data: DATA.cnus_weeks },
  yAxis: { type: 'value', name: '%', max: 100 },
  series: [
    { name: '中国模型', type: 'line', stack: 'total', areaStyle: { color: '#EF4444' },
      data: DATA.cnus_cn, itemStyle: { color: '#EF4444' } },
    { name: '美国模型', type: 'line', stack: 'total', areaStyle: { color: '#3B82F6' },
      data: DATA.cnus_us, itemStyle: { color: '#3B82F6' } }
  ]
});

// ============== Chart 8: 资产价格 ==============
const chart8 = echarts.init(document.getElementById('chart-assets'));
const assetSeries = Object.entries(DATA.asset_series).map(([t, vals]) => ({
  name: t, type: 'line', smooth: true, data: vals, symbol: 'none', lineStyle: { width: 1.5 }
}));
chart8.setOption({
  tooltip: { trigger: 'axis' },
  legend: { top: 0, type: 'scroll' },
  grid: { left: 50, right: 30, bottom: 50, top: 40 },
  xAxis: { type: 'category', data: DATA.asset_dates, axisLabel: { rotate: 45, fontSize: 11 } },
  yAxis: { type: 'value', name: '指数(起=100)' },
  series: assetSeries
});

// ============== Chart 9: MoM ==============
const chart9 = echarts.init(document.getElementById('chart-mom'));
chart9.setOption({
  tooltip: { trigger: 'axis', formatter: '{b}: {c}%' },
  grid: { left: 70, right: 30, bottom: 30, top: 10 },
  xAxis: { type: 'value', name: '%', axisLine: { onZero: true } },
  yAxis: { type: 'category', data: DATA.mom_names, axisLabel: { fontSize: 11 } },
  series: [{
    type: 'bar', data: DATA.mom_values,
    itemStyle: { color: function(p) { return p.value >= 0 ? '#10b981' : '#ef4444'; } },
    label: { show: true, position: 'right', formatter: '{c}%' }
  }]
});

// ============== Chart 10: 资产类别 ==============
const chart10 = echarts.init(document.getElementById('chart-asset-cat'));
chart10.setOption({
  tooltip: { trigger: 'item' },
  legend: { bottom: 0, type: 'scroll' },
  series: [{
    type: 'pie', radius: '60%',
    data: [
      { value: 3, name: 'GPU/芯片核心 (NVDA/TSM/AVGO)' },
      { value: 2, name: 'HBM存储 (MU/海力士)' },
      { value: 2, name: '半导体设备 (ASML/AMAT)' },
      { value: 3, name: '数据中心电力 (VRT/CEG/VST)' },
      { value: 1, name: '网络 (ANET)' },
      { value: 1, name: '中立云 (CRWV)' },
      { value: 4, name: '中国AI算力 (寒武纪等)' },
    ]
  }]
});

// ============== Chart 11: 中国云季度Capex ==============
const chartCN1 = echarts.init(document.getElementById('chart-cn-quarterly'));
chartCN1.setOption({
  tooltip: { trigger: 'axis', formatter: function(params) {
    let s = params[0].axisValue + '<br/>';
    params.forEach(p => {
      if (p.value != null) s += `<span style="display:inline-block;width:8px;height:8px;background:${p.color};border-radius:50%;margin-right:6px"></span>${p.seriesName}: ¥${p.value}亿<br/>`;
    });
    return s;
  }},
  legend: { top: 0, data: ['阿里巴巴', '腾讯', '字节跳动', '百度'] },
  grid: { left: 60, right: 30, bottom: 50, top: 40 },
  xAxis: { type: 'category', data: DATA.cn_quarters, axisLabel: { rotate: 45, fontSize: 11 } },
  yAxis: { type: 'value', name: '亿人民币', nameTextStyle: { fontSize: 11 } },
  series: [
    { name: '阿里巴巴', type: 'line', smooth: true, data: DATA.cn_series.Alibaba, itemStyle: { color: '#FF6A00' } },
    { name: '腾讯', type: 'line', smooth: true, data: DATA.cn_series.Tencent, itemStyle: { color: '#0095FF' } },
    { name: '字节跳动', type: 'line', smooth: true, data: DATA.cn_series.ByteDance, itemStyle: { color: '#000000' } },
    { name: '百度', type: 'line', smooth: true, data: DATA.cn_series.Baidu, itemStyle: { color: '#2932E1' } },
  ]
});

// ============== Chart 12: 中美年度Capex对比 ==============
const chartCN2 = echarts.init(document.getElementById('chart-cn-us-compare'));
chartCN2.setOption({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  legend: { top: 0, data: ['美国四大', '中国四大'] },
  grid: { left: 50, right: 20, bottom: 30, top: 40 },
  xAxis: { type: 'category', data: DATA.cn_us_years },
  yAxis: { type: 'value', name: '亿美元' },
  series: [
    { name: '美国四大', type: 'bar', data: DATA.us_annual_usd, itemStyle: { color: '#3B82F6' } },
    { name: '中国四大', type: 'bar', data: DATA.cn_annual_usd, itemStyle: { color: '#EF4444' } }
  ]
});

// ============== Chart 13: 中国云2025占比 ==============
const chartCN3 = echarts.init(document.getElementById('chart-cn-pie'));
chartCN3.setOption({
  tooltip: { trigger: 'item', formatter: '{b}: ¥{c}B ({d}%)' },
  legend: { bottom: 0 },
  series: [{
    type: 'pie', radius: ['40%', '70%'],
    data: DATA.cn_2025_pie,
    label: { formatter: '{b}\n¥{c}亿' }
  }]
});

// ============== Chart 14: TSMC月度营收 ==============
const chartTSMC = echarts.init(document.getElementById('chart-tsmc'));
chartTSMC.setOption({
  tooltip: { trigger: 'axis', formatter: function(p) {
    return p[0].axisValue + '<br/>营收: $' + p[0].value + 'B<br/>YoY: ' + (DATA.tsmc_yoy[p[0].dataIndex] || 0) + '%';
  }},
  grid: { left: 60, right: 60, bottom: 50, top: 30 },
  xAxis: { type: 'category', data: DATA.tsmc_months, axisLabel: { rotate: 45, fontSize: 11 } },
  yAxis: [
    { type: 'value', name: '亿美元', position: 'left' },
    { type: 'value', name: 'YoY %', position: 'right', axisLabel: { formatter: '{value}%' } },
  ],
  series: [
    { type: 'bar', data: DATA.tsmc_revenue, itemStyle: { color: '#06B6D4' }, name: '月营收' },
    { type: 'line', yAxisIndex: 1, data: DATA.tsmc_yoy, itemStyle: { color: '#F59E0B' }, name: 'YoY', smooth: true },
  ]
});

// ============== Chart 15: 韩国半导体出口 ==============
const chartKorea = echarts.init(document.getElementById('chart-korea'));
chartKorea.setOption({
  tooltip: { trigger: 'axis' },
  legend: { top: 0, data: ['总出口', '存储芯片'] },
  grid: { left: 50, right: 30, bottom: 50, top: 40 },
  xAxis: { type: 'category', data: DATA.korea_months, axisLabel: { rotate: 45, fontSize: 11 } },
  yAxis: { type: 'value', name: '亿美元' },
  series: [
    { name: '总出口', type: 'line', data: DATA.korea_total, itemStyle: { color: '#3B82F6' }, smooth: true, areaStyle: {opacity: 0.2} },
    { name: '存储芯片', type: 'line', data: DATA.korea_memory, itemStyle: { color: '#EF4444' }, smooth: true },
  ]
});

// ============== Chart 16: AI vs BTC 电力 ==============
const chartPower = echarts.init(document.getElementById('chart-power'));
chartPower.setOption({
  tooltip: { trigger: 'axis', formatter: function(p) {
    let s = p[0].axisValue + '<br/>';
    p.forEach(x => { s += `${x.seriesName}: ${x.value} TWh<br/>` });
    return s;
  }},
  legend: { top: 0, data: ['AI数据中心', 'BTC挖矿', '其他加密'] },
  grid: { left: 50, right: 30, bottom: 30, top: 40 },
  xAxis: { type: 'category', data: DATA.power_years },
  yAxis: { type: 'value', name: 'TWh/年' },
  series: [
    { name: 'AI数据中心', type: 'bar', data: DATA.power_ai, itemStyle: { color: '#10B981' } },
    { name: 'BTC挖矿', type: 'bar', data: DATA.power_btc, itemStyle: { color: '#F59E0B' } },
    { name: '其他加密', type: 'bar', data: DATA.power_crypto, itemStyle: { color: '#A78BFA' } },
  ]
});

// Responsive
window.addEventListener('resize', () => {
  [chart1, chart2, chart3, chart4, chart5, chart6, chart7, chart8, chart9, chart10,
   chartCN1, chartCN2, chartCN3, chartTSMC, chartKorea, chartPower].forEach(c => c.resize());
});
</script>

</body>
</html>
"""


def render_event_html(events):
    html_parts = []
    for ev in events:
        cat = ev["category"]
        badge_cls = {
            "capex": "badge-capex",
            "token": "badge-token",
            "investment": "badge-investment"
        }.get(cat, "badge-capex")
        cat_label = {"capex": "Capex", "token": "Token", "investment": "投资"}.get(cat, cat)
        stars = "⭐" * (ev.get("severity") or 3)
        title_safe = (ev["title"] or "").replace("<", "&lt;").replace(">", "&gt;")
        url = ev.get("url", "")
        source = ev.get("source_name", "")
        pub = (ev.get("published_at") or "")[:10]
        ents = ""
        try:
            ent_list = json.loads(ev.get("entities") or "[]")
            if ent_list:
                ents = " · " + ", ".join(ent_list[:4])
        except Exception:
            pass
        html_parts.append(f"""
          <li class="event-item">
            <span class="event-badge {badge_cls}">{cat_label}</span>
            <div class="event-content">
              <div class="event-title">
                <a href="{url}" target="_blank">{title_safe}</a>
                <span class="severity-stars">{stars}</span>
              </div>
              <div class="event-meta">{source} · {pub}{ents}</div>
            </div>
          </li>""")
    if not html_parts:
        return '<li class="event-item"><div class="event-content"><div class="event-meta">暂无近期事件。等待首次扫描完成。</div></div></li>'
    return "".join(html_parts)


def main():
    capex_q = query_capex_quarterly()
    guidance = query_capex_guidance()
    token_m = query_token_monthly()
    models = query_model_weekly()
    assets = query_assets()
    events = query_recent_events(limit=50, min_severity=3)
    china_capex = query_china_capex()
    tsmc = query_tsmc()
    korea = query_korea()
    power = query_power()

    # 准备数据
    cap_quarters, cap_series = prep_capex_quarterly_data(capex_q)
    ann_years, ann_actual = prep_capex_annual(capex_q, guidance)

    # Q1 2026 饼图
    q1_rows = [r for r in capex_q if r["calendar_year"] == 2026 and r["calendar_quarter"] == 1]
    q1_pie = [{"name": COMPANY_NAMES[r["company"]], "value": r["capex_billion_usd"]} for r in q1_rows]

    # 指引时间线
    g_dates = sorted(set(g["announced_date"] for g in guidance if g["guidance_year"] == 2026))
    g_series = {c: [] for c in COMPANY_NAMES}
    for d in g_dates:
        for c in COMPANY_NAMES:
            match = [g for g in guidance if g["company"] == c
                     and g["guidance_year"] == 2026 and g["announced_date"] == d]
            if match:
                g_series[c].append(match[0]["guidance_point_billion"])
            else:
                # carry-forward 前一个值
                prev = [g for g in guidance if g["company"] == c
                        and g["guidance_year"] == 2026 and g["announced_date"] <= d]
                if prev:
                    g_series[c].append(sorted(prev, key=lambda x: x["announced_date"])[-1]["guidance_point_billion"])
                else:
                    g_series[c].append(None)

    # Token 平台月度
    token_months, token_series = prep_token_monthly_data(token_m)

    # Top 10 最新
    latest_week, top10 = prep_model_ranking_latest(models)
    top10_names = [r["model_name"] for r in top10]
    top10_data = [r["tokens_trillion"] for r in top10]
    top10_colors = ["#EF4444" if r["country"] == "CN" else "#3B82F6" for r in top10]

    # 中美占比
    cnus_weeks, cnus_cn, cnus_us = prep_china_vs_us_share(models)

    # 资产价格
    asset_dates, asset_series = prep_asset_prices(assets)

    # MoM
    mom_names, mom_values = [], []
    for t, vals in asset_series.items():
        # 取最后两个非空值
        non_null = [v for v in vals if v is not None]
        if len(non_null) >= 2:
            mom = round((non_null[-1] - non_null[-2]) / non_null[-2] * 100, 1)
            mom_names.append(t)
            mom_values.append(mom)

    # 提前计算 guidance_2026 和 capex_2025 供后续中美对比使用
    guidance_2026 = {}
    for g in sorted(guidance, key=lambda x: x["announced_date"]):
        if g["guidance_year"] == 2026:
            guidance_2026[g["company"]] = g["guidance_point_billion"] or 0
    capex_2025 = round(sum(r["capex_billion_usd"] for r in capex_q if r["calendar_year"] == 2025), 1)

    # ---------- 中国云数据加工 ----------
    cn_companies = ["Alibaba", "Tencent", "ByteDance", "Baidu"]
    cn_quarters = sorted(set(f"{r['calendar_year']} Q{r['calendar_quarter']}" for r in china_capex))
    cn_series = {c: [] for c in cn_companies}
    for q in cn_quarters:
        yr, qt = q.split(" Q")
        for c in cn_companies:
            match = [r for r in china_capex if r["company"] == c
                     and r["calendar_year"] == int(yr) and r["calendar_quarter"] == int(qt)]
            cn_series[c].append(match[0]["capex_billion_cny"] if match else None)

    # 中美年度对比
    years_cmp = [2024, 2025, 2026]
    us_annual_usd = []
    cn_annual_usd = []
    for y in years_cmp:
        us_total = sum(r["capex_billion_usd"] for r in capex_q if r["calendar_year"] == y)
        cn_total = sum(r["capex_billion_usd"] or 0 for r in china_capex if r["calendar_year"] == y)
        # 2026只有Q1，需估算全年
        if y == 2026:
            us_q1 = us_total
            cn_q1 = cn_total
            # 用2026指引代替
            us_total = sum(guidance_2026.values())
            cn_total = cn_q1 * 4  # 粗略外推
        us_annual_usd.append(round(us_total, 1))
        cn_annual_usd.append(round(cn_total, 1))

    # 2025中国云占比
    cn_2025_pie = []
    for c in cn_companies:
        v = sum(r["capex_billion_cny"] for r in china_capex
                if r["company"] == c and r["calendar_year"] == 2025)
        if v > 0:
            cn_2025_pie.append({"name": c, "value": round(v, 1)})

    # 中国云关键指标
    cn_capex_2025_cny = round(sum(r["capex_billion_cny"] for r in china_capex if r["calendar_year"] == 2025), 1)
    cn_capex_2025_usd = round(sum(r["capex_billion_usd"] or 0 for r in china_capex if r["calendar_year"] == 2025), 1)
    cn_capex_q1_cny = round(sum(r["capex_billion_cny"] for r in china_capex
                                if r["calendar_year"] == 2026 and r["calendar_quarter"] == 1), 1)
    cn_capex_q1_prev = round(sum(r["capex_billion_cny"] for r in china_capex
                                  if r["calendar_year"] == 2025 and r["calendar_quarter"] == 1), 1) or 1
    cn_capex_q1_yoy = round((cn_capex_q1_cny - cn_capex_q1_prev) / cn_capex_q1_prev * 100, 1)
    bytedance_q1 = round(sum(r["capex_billion_cny"] for r in china_capex
                              if r["company"] == "ByteDance"
                              and r["calendar_year"] == 2026 and r["calendar_quarter"] == 1), 1)
    cn_vs_us_ratio = round((cn_capex_2025_usd / max(capex_2025, 1)) * 100, 1)

    # ---------- TSMC 数据加工 ----------
    tsmc_months = [f"{r['year']}-{r['month']:02d}" for r in tsmc]
    tsmc_revenue = [r["revenue_billion_usd"] for r in tsmc]
    tsmc_yoy = [r["yoy_pct"] for r in tsmc]
    tsmc_latest = tsmc[-1] if tsmc else {}
    tsmc_latest_usd = tsmc_latest.get("revenue_billion_usd", 0)
    tsmc_latest_period = f"{tsmc_latest.get('year')}年{tsmc_latest.get('month')}月" if tsmc_latest else ""
    tsmc_latest_yoy = tsmc_latest.get("yoy_pct", 0)

    # ---------- 韩国数据加工 ----------
    korea_months = [f"{r['year']}-{r['month']:02d}" for r in korea]
    korea_total = [r["exports_billion_usd"] for r in korea]
    korea_memory = [r["memory_billion_usd"] for r in korea]
    korea_latest = korea[-1] if korea else {}

    # ---------- 电力数据加工 ----------
    power_years = sorted(set(r["year"] for r in power))
    power_ai = [next((r["twh_per_year"] for r in power if r["year"] == y and r["category"] == "ai_datacenter"), 0) for y in power_years]
    power_btc = [next((r["twh_per_year"] for r in power if r["year"] == y and r["category"] == "btc_mining"), 0) for y in power_years]
    power_crypto = [next((r["twh_per_year"] for r in power if r["year"] == y and r["category"] == "crypto_other"), 0) for y in power_years]

    # 组装 JSON
    payload = {
        "capex_quarters": cap_quarters,
        "capex_series": cap_series,
        "annual_years": ann_years,
        "annual_actual": ann_actual,
        "q1_2026_pie": q1_pie,
        "guidance_dates": g_dates,
        "guidance_series": g_series,
        "token_months": token_months,
        "token_series": token_series,
        "top10_week": latest_week,
        "top10_names": top10_names,
        "top10_data": top10_data,
        "top10_colors": top10_colors,
        "cnus_weeks": cnus_weeks,
        "cnus_cn": cnus_cn,
        "cnus_us": cnus_us,
        "asset_dates": asset_dates,
        "asset_series": asset_series,
        "mom_names": mom_names,
        "mom_values": mom_values,
        # 中国云
        "cn_quarters": cn_quarters,
        "cn_series": cn_series,
        "cn_us_years": [str(y) for y in years_cmp],
        "us_annual_usd": us_annual_usd,
        "cn_annual_usd": cn_annual_usd,
        "cn_2025_pie": cn_2025_pie,
        # TSMC
        "tsmc_months": tsmc_months,
        "tsmc_revenue": tsmc_revenue,
        "tsmc_yoy": tsmc_yoy,
        # 韩国
        "korea_months": korea_months,
        "korea_total": korea_total,
        "korea_memory": korea_memory,
        # 电力
        "power_years": [str(y) for y in power_years],
        "power_ai": power_ai,
        "power_btc": power_btc,
        "power_crypto": power_crypto,
    }

    stats = f"{len(capex_q)}条Capex · {len(token_m)}条Token · {len(models)}条模型 · {len(assets)}条价格 · {len(events)}条事件"

    # ---------- 动态计算 Capex 卡片 ----------
    # 最新季度
    latest_q_rows = sorted(capex_q, key=lambda x: (x["calendar_year"], x["calendar_quarter"]))
    if latest_q_rows:
        latest_y = latest_q_rows[-1]["calendar_year"]
        latest_qt = latest_q_rows[-1]["calendar_quarter"]
    else:
        latest_y, latest_qt = 2026, 1
    latest_q_total = round(sum(r["capex_billion_usd"] for r in capex_q
                               if r["calendar_year"] == latest_y and r["calendar_quarter"] == latest_qt), 1)
    prev_q_total = round(sum(r["capex_billion_usd"] for r in capex_q
                             if r["calendar_year"] == latest_y - 1 and r["calendar_quarter"] == latest_qt), 1) or 1
    latest_q_yoy = round((latest_q_total - prev_q_total) / prev_q_total * 100, 1)

    # 2026指引合计（guidance_2026已在前面计算）
    capex_guidance_2026 = round(sum(guidance_2026.values()), 1)

    # 2025全年 (capex_2025已在前面计算)
    capex_2024 = sum(r["capex_billion_usd"] for r in capex_q if r["calendar_year"] == 2024) or 1
    capex_2025_yoy = round((capex_2025 - capex_2024) / capex_2024 * 100, 1)
    guidance_yoy = round((capex_guidance_2026 - capex_2025) / max(capex_2025, 1) * 100, 1)

    # ---------- 动态计算 Token 卡片 ----------
    # 头部平台最新月日均合计
    latest_month = max((f"{r['year']}-{r['month']:02d}" for r in token_m), default="2026-01")
    ly, lm = latest_month.split("-")
    daily_total = round(sum(r["daily_avg_trillion"] or 0 for r in token_m
                            if r["year"] == int(ly) and r["month"] == int(lm)
                            and r["platform"] in ["gemini", "gpt", "doubao", "qwen", "microsoft_foundry"]), 1)
    # 豆包最新
    doubao_rows = sorted([r for r in token_m if r["platform"] == "doubao"],
                         key=lambda x: (x["year"], x["month"]))
    doubao_daily = doubao_rows[-1]["daily_avg_trillion"] if doubao_rows else 0
    doubao_period = f"{doubao_rows[-1]['year']}年{doubao_rows[-1]['month']}月" if doubao_rows else ""

    # OpenRouter中美份额（最新周）
    latest_week_models = [r for r in models if r["week_start"] == (max((r["week_start"] for r in models), default=None))]
    cn_tokens = sum(r["tokens_trillion"] for r in latest_week_models if r["country"] == "CN")
    us_tokens = sum(r["tokens_trillion"] for r in latest_week_models if r["country"] == "US")
    total_or = cn_tokens + us_tokens
    cn_share = round(cn_tokens / total_or * 100, 1) if total_or > 0 else 0
    cn_share_period = latest_week_models[0]["week_start"] if latest_week_models else ""
    or_weekly = round(total_or, 1)

    html = HTML_TEMPLATE \
        .replace("__UPDATED_AT__", datetime.now().strftime("%Y-%m-%d %H:%M")) \
        .replace("__STATS__", stats) \
        .replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False)) \
        .replace("__EVENT_LIST_HTML__", render_event_html(events)) \
        .replace("__CAPEX_GUIDANCE_2026__", str(capex_guidance_2026)) \
        .replace("__CAPEX_GUIDANCE_YOY__", f"+{guidance_yoy}%" if guidance_yoy > 0 else f"{guidance_yoy}%") \
        .replace("__CAPEX_LATEST_Q__", str(latest_q_total)) \
        .replace("__CAPEX_LATEST_Q_LABEL__", f"{latest_y} Q{latest_qt}") \
        .replace("__CAPEX_LATEST_Q_YOY__", f"+{latest_q_yoy}%" if latest_q_yoy > 0 else f"{latest_q_yoy}%") \
        .replace("__CAPEX_2025__", str(capex_2025)) \
        .replace("__CAPEX_2025_YOY__", f"+{capex_2025_yoy}%" if capex_2025_yoy > 0 else f"{capex_2025_yoy}%") \
        .replace("__TOKEN_DAILY_TOTAL__", str(daily_total)) \
        .replace("__TOKEN_DAILY_PERIOD__", f"{ly}年{int(lm)}月") \
        .replace("__DOUBAO_DAILY__", str(doubao_daily)) \
        .replace("__DOUBAO_PERIOD__", doubao_period) \
        .replace("__CN_SHARE__", str(cn_share)) \
        .replace("__CN_SHARE_PERIOD__", cn_share_period) \
        .replace("__OR_WEEKLY__", str(or_weekly)) \
        .replace("__OR_WEEKLY_PERIOD__", f"week of {cn_share_period}" if cn_share_period else "") \
        .replace("__CN_CAPEX_2025__", str(cn_capex_2025_cny)) \
        .replace("__CN_CAPEX_2025_USD__", str(cn_capex_2025_usd)) \
        .replace("__CN_CAPEX_Q1__", str(cn_capex_q1_cny)) \
        .replace("__CN_CAPEX_Q1_YOY__", f"+{cn_capex_q1_yoy}%" if cn_capex_q1_yoy > 0 else f"{cn_capex_q1_yoy}%") \
        .replace("__BYTEDANCE_Q1__", f"¥{bytedance_q1}") \
        .replace("__CN_VS_US_RATIO__", str(cn_vs_us_ratio)) \
        .replace("__TSMC_LATEST__", str(tsmc_latest_usd)) \
        .replace("__TSMC_LATEST_PERIOD__", tsmc_latest_period) \
        .replace("__TSMC_LATEST_YOY__", f"+{tsmc_latest_yoy}%" if tsmc_latest_yoy > 0 else f"{tsmc_latest_yoy}%") \
        .replace("__KOREA_LATEST__", str(korea_latest.get("exports_billion_usd", 0)) if korea_latest else "0") \
        .replace("__KOREA_LATEST_PERIOD__", f"{korea_latest.get('year')}年{korea_latest.get('month')}月" if korea_latest else "") \
        .replace("__KOREA_LATEST_YOY__", f"+{korea_latest.get('yoy_pct', 0)}%" if korea_latest else "0%")

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"✅ HTML rendered to {OUT_HTML}")
    return OUT_HTML


if __name__ == "__main__":
    main()
