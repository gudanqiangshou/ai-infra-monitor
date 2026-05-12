#!/usr/bin/env python3
# curate.py - 精选 Top N 事件
"""
策略：
1. 每条事件打综合分（severity / impact / 新鲜度 / 来源权威性）
2. 按类别均衡分配（capex/token/investment 各取若干）
3. 兜底：如某类别不足，从其他类别补齐

输出：Top N 事件列表，按综合分排序
"""
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

# 权威来源加分
AUTHORITY_DOMAINS = {
    "reuters.com": 2, "bloomberg.com": 2, "ft.com": 2, "wsj.com": 2,
    "cnbc.com": 1, "nikkei.com": 1, "fortune.com": 1,
    "openrouter.ai": 2, "a16z.com": 1,
    "datacenterdynamics.com": 1, "techcrunch.com": 1,
    "wallstreetcn.com": 1, "caixin.com": 1, "36kr.com": 1,
    "cls.cn": 1, "qbitai.com": 1,
}

# 黑名单：非新闻源（聚合/视频/社交媒体易返回旧内容）
SOURCE_BLACKLIST = {
    # 视频/社交
    "youtube.com", "facebook.com", "linkedin.com", "twitter.com", "x.com",
    "reddit.com", "tiktok.com", "instagram.com", "weibo.com", "zhihu.com",
    # 财经聚合（常返回历史回顾文章）
    "yahoo.com", "finance.yahoo.com", "investing.com", "biggo.com",
    "seekingalpha.com", "fool.com", "marketbeat.com", "benzinga.com",
    "tipranks.com", "zacks.com", "marketwatch.com",
    # 二手分析/博客平台
    "letsdatascience.com", "substack.com", "medium.com", "wordpress.com",
    "blogspot.com", "tumblr.com",
    # AI 内容农场
    "tech-insider.org",
}

# 每类别目标条数（总和 10）
CATEGORY_QUOTA = {"capex": 4, "token": 3, "investment": 3}


def score_event(ev: dict) -> float:
    """综合评分"""
    score = (ev.get("severity") or 3) * 10

    # 利好/利空（非中性）+3
    if ev.get("impact") in ("positive", "negative"):
        score += 3

    # 新鲜度
    pub = ev.get("published_at") or ""
    try:
        pub_d = datetime.fromisoformat(pub.split("T")[0])
        days_ago = (datetime.now() - pub_d).days
        if days_ago <= 1:
            score += 2
        elif days_ago <= 3:
            score += 1
    except Exception:
        pass

    # 来源权威性
    source = (ev.get("source_name") or "").lower()
    for domain, bonus in AUTHORITY_DOMAINS.items():
        if domain in source:
            score += bonus
            break

    return score


def get_top_curated(window_days: int = 7, n: int = 10, only_unpushed: bool = False,
                    min_severity: int = 3):
    """精选 Top N

    window_days: 时间窗口（默认7天，飞书日报建议2-3）
    n: 总数（默认10）
    only_unpushed: 只挑未推送过的（用于飞书事件驱动）
    min_severity: 候选最低重要性
    """
    conn = get_conn()
    cur = conn.cursor()

    cutoff_disc = (datetime.now() - timedelta(days=window_days)).isoformat()
    cutoff_pub = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    # 硬门禁 (Codex 建议)：默认只接受确定新鲜的新闻
    # 1. discovered_at 在窗口内
    # 2. published_at 必须存在且 >= 窗口起点
    # 3. content_freshness 必须是 'recent' （Claude 已确认）
    # 4. translated_title 必须已存在（确认 Claude 已处理）
    # 5. date_source != 'unknown' （日期可信）
    sql = """
        SELECT id, category, title, translated_title, summary, url, source_name,
               published_at, discovered_at, severity, entities, impact, thesis,
               content_freshness, date_source
        FROM news_events
        WHERE discovered_at >= ?
          AND published_at IS NOT NULL
          AND published_at != ''
          AND published_at >= ?
          AND severity >= ?
          AND content_freshness = 'recent'
          AND translated_title IS NOT NULL
          AND translated_title != ''
          AND COALESCE(date_source, 'unknown') != 'unknown'
          AND published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    """
    params = [cutoff_disc, cutoff_pub, min_severity]
    if only_unpushed:
        sql += " AND pushed = 0"
    sql += " ORDER BY discovered_at DESC"

    cur.execute(sql, params)
    all_events = [dict(r) for r in cur.fetchall()]
    conn.close()

    # 移除黑名单源
    all_events = [e for e in all_events
                  if not any(bl in (e.get("source_name") or "").lower()
                             for bl in SOURCE_BLACKLIST)]

    if not all_events:
        return []

    # 打分排序
    for ev in all_events:
        ev["_score"] = score_event(ev)
    all_events.sort(key=lambda x: x["_score"], reverse=True)

    # 按类别均衡分配
    by_cat = {"capex": [], "token": [], "investment": []}
    for ev in all_events:
        c = ev.get("category", "investment")
        if c in by_cat:
            by_cat[c].append(ev)

    # 第一轮：按配额取
    selected = []
    for cat, quota in CATEGORY_QUOTA.items():
        selected.extend(by_cat[cat][:quota])

    # 如不足 n，按总分补齐（不重复）
    selected_ids = {e["id"] for e in selected}
    for ev in all_events:
        if len(selected) >= n:
            break
        if ev["id"] not in selected_ids:
            selected.append(ev)
            selected_ids.add(ev["id"])

    # 截断 + 按分数重排
    selected = sorted(selected[:n], key=lambda x: x["_score"], reverse=True)

    # 清理临时字段
    for ev in selected:
        ev.pop("_score", None)

    return selected


def main():
    """命令行预览精选结果"""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--n", type=int, default=10)
    args = p.parse_args()

    events = get_top_curated(window_days=args.days, n=args.n)
    print(f"=== 精选 Top {len(events)} ({args.days}天窗口) ===\n")
    for i, ev in enumerate(events, 1):
        cat_label = {"capex": "💰Capex", "token": "🚀Token", "investment": "📈投资"}.get(
            ev.get("category"), "?")
        stars = "⭐" * (ev.get("severity") or 3)
        impact_emoji = {"positive": "📈", "negative": "📉"}.get(ev.get("impact"), "")
        title = ev.get("translated_title") or ev.get("title") or ""
        print(f"{i}. [{cat_label}] {stars} {impact_emoji}")
        print(f"   {title}")
        if ev.get("thesis"):
            print(f"   💡 {ev['thesis']}")
        print(f"   {ev.get('source_name')} · {(ev.get('published_at') or '')[:10]}")
        print()


if __name__ == "__main__":
    main()
