# AI Infra Monitor

> 四大云厂商 Capex + 全球AI Token 消耗 + 投资关联资产 监控系统

## 🎯 系统概览

- **Capex 监控**: Amazon / Microsoft / Alphabet / Meta 季度Capex、指引变更
- **Token 消耗**: Gemini / GPT / 豆包 / 通义千问 / OpenRouter Top10模型
- **投资关联**: NVDA / TSM / HBM / 电力 / 网络 / 中国AI算力链
- **事件驱动**: 仅当有新事件时推送飞书，避免噪声
- **Dashboard**: https://gudanqiangshou.github.io/ai-infra-monitor/

## 🏗 架构

```
scripts/
├── db.py                # SQLite 数据库
├── backfill_capex.py    # 2022Q1-2026Q1历史Capex回填
├── backfill_token.py    # 历史Token消耗 + OpenRouter周度
├── backfill_assets.py   # NVDA/TSM等资产价格回填
├── fetch_news.py        # Tavily每日新闻抓取+去重
├── render_html.py       # ECharts可视化 (4 Tab Dashboard)
├── feishu_notifier.py   # 飞书post富文本通知
└── main.py              # 主调度器
```

## 🕐 调度

- **每日 08:30**: LaunchAgent `com.a1.ai-infra-monitor` 触发
- **事件驱动**: 仅当 severity ≥ 3 时推送飞书
- **周日**: 强制推送周度趋势汇总
- **每月1日**: 月度深度报告

## 📊 Dashboard 4个 Tab

1. **💰 Capex Dashboard** - 季度趋势、年度堆叠、指引时间线
2. **🚀 Token Dashboard** - 平台月度、Top10模型、中美占比
3. **📈 投资关联** - 核心受益股归一化走势、MoM变动、资产分类
4. **📰 今日要闻** - 时间倒序高重要性事件

## 🔧 手动运行

```bash
cd /Users/a1/Code/ai-infra-monitor
./run_daily.sh                          # 完整流程
./run_daily.sh --skip-deploy --skip-notify  # 仅本地预览
./run_daily.sh --force-weekly           # 强制推送周报
```

## 📦 数据回填

```bash
python3 scripts/backfill_capex.py
python3 scripts/backfill_token.py
python3 scripts/backfill_assets.py
```

## 🚨 已知数据局限

- 豆包、通义千问的**模型级**月度Token数据不对外公开（仅平台级汇总）
- Anthropic 从未官方公开 Token 消耗量（用收入推算）
- 开源模型本地部署的 Token 无法统计
- OpenRouter 仅占全球总量 ~1-2%，但趋势代表性强

## 🔒 凭证管理

所有 secret 存放在 `.env.local`（已 git-ignore），包括：
- `TAVILY_API_KEY` - 新闻搜索
- `FEISHU_WEBHOOK` - 飞书通知
- `GITHUB_TOKEN` - Pages 部署
