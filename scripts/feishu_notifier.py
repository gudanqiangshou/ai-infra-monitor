#!/usr/bin/env python3
# feishu_notifier.py - 飞书 post 富文本通知
"""
事件驱动:
- 有 severity >= 3 的新事件: 推送
- 无新事件: 静默
- 每周日: 周度趋势汇总
- 每月1日: 月度深度报告
"""
import os
import sys
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
DASHBOARD_URL = os.environ.get(
    "DASHBOARD_URL",
    "https://gudanqiangshou.github.io/ai-infra-monitor/"
)


# ======================================================================
# Domain → 友好标签
# ======================================================================
DOMAIN_LABELS = {
    "reuters.com": "Reuters", "bloomberg.com": "Bloomberg", "ft.com": "FT",
    "cnbc.com": "CNBC", "wsj.com": "WSJ", "fortune.com": "Fortune",
    "tomshardware.com": "Tom's Hardware", "datacenterdynamics.com": "DCD",
    "openrouter.ai": "OpenRouter", "a16z.com": "a16z",
    "techcrunch.com": "TechCrunch",
    "wallstreetcn.com": "华尔街见闻", "caixin.com": "财新", "yicai.com": "第一财经",
    "36kr.com": "36氪", "qbitai.com": "量子位", "cls.cn": "财联社",
    "sina.com.cn": "新浪", "163.com": "网易", "qq.com": "腾讯新闻",
    "stcn.com": "证券时报", "21jingji.com": "21财经", "jiemian.com": "界面",
}


def domain_label(url: str) -> str:
    if not url:
        return ""
    try:
        host = url.split("/")[2].lower().removeprefix("www.")
        if host in DOMAIN_LABELS:
            return DOMAIN_LABELS[host]
        for d, lbl in DOMAIN_LABELS.items():
            if host.endswith(d):
                return lbl
        parts = host.split(".")
        return parts[-2] if len(parts) >= 2 else host
    except Exception:
        return "来源"


def get_unpushed_events(min_severity: int = 3):
    """获取未推送的高重要性事件 — 用精选 Top 10"""
    from curate import get_top_curated
    # 只取未推送的精选
    return get_top_curated(window_days=7, n=10, only_unpushed=True)


def mark_events_pushed(event_ids):
    if not event_ids:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany("""
        UPDATE news_events SET pushed = 1, pushed_at = ? WHERE id = ?
    """, [(datetime.now().isoformat(), eid) for eid in event_ids])
    conn.commit()
    conn.close()


def get_key_metrics():
    """获取关键指标摘要"""
    conn = get_conn()
    cur = conn.cursor()

    # 最新季度Capex
    cur.execute("""
        SELECT SUM(capex_billion_usd) as total
        FROM capex_quarterly
        WHERE calendar_year = 2026 AND calendar_quarter = 1
    """)
    q1_total = (cur.fetchone()["total"] or 0)

    # 2026指引合计（取每家最新）
    cur.execute("""
        SELECT company, MAX(announced_date) as latest
        FROM capex_guidance
        WHERE guidance_year = 2026
        GROUP BY company
    """)
    latest_dates = {r["company"]: r["latest"] for r in cur.fetchall()}
    guidance_total = 0
    for c, d in latest_dates.items():
        cur.execute("""
            SELECT guidance_point_billion FROM capex_guidance
            WHERE company=? AND guidance_year=2026 AND announced_date=?
            LIMIT 1
        """, (c, d))
        row = cur.fetchone()
        if row:
            guidance_total += row["guidance_point_billion"] or 0

    # 最新OpenRouter Top 1
    cur.execute("""
        SELECT model_name, tokens_trillion, week_start
        FROM token_model_weekly
        WHERE rank = 1
        ORDER BY week_start DESC
        LIMIT 1
    """)
    top1_row = cur.fetchone()
    top1 = dict(top1_row) if top1_row else None

    # 全球总量（最新月）
    cur.execute("""
        SELECT SUM(daily_avg_trillion) as total
        FROM token_monthly
        WHERE platform IN ('gemini', 'gpt', 'doubao', 'qwen', 'microsoft_foundry')
          AND (year, month) = (
            SELECT year, month FROM token_monthly
            WHERE platform = 'doubao'
            ORDER BY year DESC, month DESC LIMIT 1
          )
    """)
    daily_total_row = cur.fetchone()
    daily_total = daily_total_row["total"] if daily_total_row else None

    conn.close()
    return {
        "q1_capex_total": round(q1_total, 1),
        "guidance_2026_total": round(guidance_total, 1),
        "top1_model": top1,
        "daily_token_total": round(daily_total, 1) if daily_total else None,
    }


def _txt(text: str, color: str = None) -> dict:
    d = {"tag": "text", "text": text}
    if color:
        d["text_color"] = color
    return d


def _link(label: str, href: str) -> dict:
    return {"tag": "a", "text": label, "href": href}


def _empty_line():
    return [_txt("")]


def build_event_message(events: list, metrics: dict) -> dict:
    """构建事件驱动通知"""
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()]

    content = []

    # Header
    content.append([_txt(f"📅 {today} {weekday} · 共 {len(events)} 条新事件")])
    content.append(_empty_line())

    # 关键指标
    content.append([_txt("📊 关键指标", color="blue")])
    if metrics["q1_capex_total"]:
        content.append([_txt(f"• 四大Capex 2026Q1合计：${metrics['q1_capex_total']}B")])
    if metrics["guidance_2026_total"]:
        content.append([_txt(f"• 2026全年指引合计：${metrics['guidance_2026_total']}B")])
    if metrics["top1_model"]:
        tm = metrics["top1_model"]
        content.append([_txt(f"• OpenRouter冠军：{tm['model_name']} ({tm['tokens_trillion']}T/周)")])
    if metrics["daily_token_total"]:
        content.append([_txt(f"• 头部平台日均Token：~{metrics['daily_token_total']}T")])
    content.append(_empty_line())

    # 事件按类别分组
    by_cat = {"capex": [], "token": [], "investment": []}
    for ev in events:
        cat = ev.get("category", "capex")
        if cat in by_cat:
            by_cat[cat].append(ev)

    cat_labels = {"capex": "💰 Capex 动态", "token": "🚀 Token & 模型", "investment": "📈 投资关联"}

    for cat, cat_events in by_cat.items():
        if not cat_events:
            continue
        content.append([_txt(cat_labels[cat], color="orange")])
        for ev in cat_events:
            stars = "⭐" * (ev.get("severity") or 3)
            impact = ev.get("impact", "")
            impact_emoji = {"positive": "📈", "negative": "📉"}.get(impact, "")
            # 优先用翻译后中文标题
            title = (ev.get("translated_title") or ev.get("title") or "")[:80]
            url = ev.get("url", "")
            src = ev.get("source_name") or domain_label(url)

            # 标题行
            line = [_txt(f"{stars}{impact_emoji} ")]
            if url:
                line.append(_link(title, url))
            else:
                line.append(_txt(title))
            line.append(_txt(f" — {src}", color="grey"))
            content.append(line)

            # 投资解读（如有）
            thesis = ev.get("thesis", "")
            if thesis:
                content.append([_txt(f"   💡 {thesis}", color="grey")])
        content.append(_empty_line())

    # 完整Dashboard链接
    content.append([_txt("━━━━━━━━━━━━━━━━", color="grey")])
    content.append([
        _txt("🔗 完整Dashboard："),
        _link("查看图表", DASHBOARD_URL)
    ])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"AI基建日报 · {today}",
                    "content": content
                }
            }
        }
    }


def build_weekly_summary(metrics: dict) -> dict:
    """每周日发送的周度汇总"""
    today = datetime.now().strftime("%Y-%m-%d")

    content = [
        [_txt(f"📅 周度汇总 · {today}")],
        _empty_line(),
        [_txt("📊 本周关键数字", color="blue")],
        [_txt(f"• 四大Capex 2026Q1合计：${metrics.get('q1_capex_total', 0)}B")],
        [_txt(f"• 2026全年指引合计：${metrics.get('guidance_2026_total', 0)}B")],
    ]
    if metrics.get("top1_model"):
        tm = metrics["top1_model"]
        content.append([_txt(f"• 模型周冠军：{tm['model_name']} ({tm['tokens_trillion']}T)")])

    content.append(_empty_line())
    content.append([_txt("━━━━━━━━━━━━━━━━", color="grey")])
    content.append([
        _txt("🔗 完整Dashboard："),
        _link("查看图表", DASHBOARD_URL)
    ])

    return {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {
            "title": f"AI基建周报 · {today}",
            "content": content
        }}}
    }


def send_feishu(message: dict) -> bool:
    if not WEBHOOK:
        print("⚠ FEISHU_WEBHOOK not set - skipping send (message dumped below):")
        print(json.dumps(message, ensure_ascii=False, indent=2)[:1500])
        return False
    try:
        resp = requests.post(WEBHOOK, json=message, timeout=15)
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            print(f"✅ feishu sent")
            return True
        else:
            print(f"❌ feishu err: {result}")
            return False
    except Exception as e:
        print(f"❌ feishu exception: {e}")
        return False


def audit_events(events: list) -> tuple:
    """推送前的二次审计 (Codex 建议)
    所有候选必须通过：
    - content_freshness == 'recent'
    - date_source != 'unknown'
    - published_at 非空且非今天的默认填充
    Returns: (clean, rejected) tuple of lists
    """
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    clean = []
    rejected = []
    for ev in events:
        reasons = []
        if (ev.get("content_freshness") or "uncertain") != "recent":
            reasons.append(f"freshness={ev.get('content_freshness') or 'NULL'}")
        ds = ev.get("date_source") or "unknown"
        if ds == "unknown":
            reasons.append("date_source=unknown")
        pub = ev.get("published_at") or ""
        if not pub:
            reasons.append("no published_at")

        if reasons:
            rejected.append({"event": ev, "reasons": reasons})
        else:
            clean.append(ev)
    return clean, rejected


def notify_if_events(min_severity: int = 3, min_4star_count: int = 3):
    """B方案智能推送：仅当 Top 10 含 ≥ N 条 4星+ 事件才推送

    min_severity: 候选事件最低重要性（默认3）
    min_4star_count: 触发推送的 4星+ 事件数量门槛（默认3）

    Codex 三道门禁:
    1. get_unpushed_events 已用 curate 硬过滤 (freshness=recent + date_source!=unknown)
    2. 这里再做 audit 二次确认
    3. 任一审计失败 → 静默 + 打印被拦截列表
    """
    events = get_unpushed_events(min_severity=min_severity)
    if not events:
        print("ℹ️ no unpushed events — silent")
        return False

    # 二次审计
    clean, rejected = audit_events(events)
    if rejected:
        print(f"⚠ audit blocked {len(rejected)} event(s):")
        for r in rejected[:5]:
            ev = r["event"]
            t = (ev.get("translated_title") or ev.get("title") or "")[:50]
            print(f"   - {t} | reasons: {', '.join(r['reasons'])}")

    if not clean:
        print("ℹ️ all candidates failed audit — silent")
        return False

    # B方案核心阈值（用通过审计的）
    n_4star_plus = sum(1 for e in clean if (e.get("severity") or 0) >= 4)
    if n_4star_plus < min_4star_count:
        print(f"ℹ️ Top {len(clean)} (post-audit) has only {n_4star_plus} ≥4★ events "
              f"— below threshold ({min_4star_count}), silent")
        return False

    metrics = get_key_metrics()
    msg = build_event_message(clean, metrics)
    ok = send_feishu(msg)
    if ok:
        mark_events_pushed([e["id"] for e in clean])
        print(f"   pushed {len(clean)} events ({n_4star_plus} ≥4★)")
    return ok


def notify_weekly():
    """周度汇总"""
    metrics = get_key_metrics()
    msg = build_weekly_summary(metrics)
    return send_feishu(msg)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["event", "weekly"], default="event")
    p.add_argument("--min-severity", type=int, default=3)
    args = p.parse_args()
    if args.mode == "event":
        notify_if_events(min_severity=args.min_severity)
    else:
        notify_weekly()
