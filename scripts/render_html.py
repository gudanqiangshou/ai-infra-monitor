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
.tabs { display: flex; background: white; border-bottom: 1px solid #e5e8eb;
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
  <div class="tab" onclick="showTab('token')">🚀 Token Dashboard</div>
  <div class="tab" onclick="showTab('invest')">📈 投资关联</div>
  <div class="tab" onclick="showTab('events')">📰 今日要闻</div>
</div>

<div class="content">

<!-- ==================== Tab 1: Capex ==================== -->
<div id="tab-capex" class="tab-pane active">

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">$695B</div>
      <div class="stat-label">2026全年指引合计</div>
      <div class="stat-delta">YoY +107%</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">$130.5B</div>
      <div class="stat-label">2026 Q1 单季合计</div>
      <div class="stat-delta">YoY +92%</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">$338B</div>
      <div class="stat-label">2025全年合计</div>
      <div class="stat-delta">YoY +34%</div>
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

<!-- ==================== Tab 2: Token ==================== -->
<div id="tab-token" class="tab-pane">

  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">~250T</div>
      <div class="stat-label">全球日均Token消耗</div>
      <div class="stat-delta">2026年3月</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">120T</div>
      <div class="stat-label">豆包日均</div>
      <div class="stat-delta">全球第3</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">51.2%</div>
      <div class="stat-label">中国模型OpenRouter份额</div>
      <div class="stat-delta">2024年仅1.2%</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">20T+</div>
      <div class="stat-label">OpenRouter周总量</div>
      <div class="stat-delta">YoY +1100%</div>
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

<!-- ==================== Tab 4: 今日要闻 ==================== -->
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

// Responsive
window.addEventListener('resize', () => {
  [chart1, chart2, chart3, chart4, chart5, chart6, chart7, chart8, chart9, chart10].forEach(c => c.resize());
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
    }

    stats = f"{len(capex_q)}条Capex · {len(token_m)}条Token · {len(models)}条模型 · {len(assets)}条价格 · {len(events)}条事件"

    html = HTML_TEMPLATE \
        .replace("__UPDATED_AT__", datetime.now().strftime("%Y-%m-%d %H:%M")) \
        .replace("__STATS__", stats) \
        .replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False)) \
        .replace("__EVENT_LIST_HTML__", render_event_html(events))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"✅ HTML rendered to {OUT_HTML}")
    return OUT_HTML


if __name__ == "__main__":
    main()
