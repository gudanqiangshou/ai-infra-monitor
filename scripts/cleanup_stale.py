#!/usr/bin/env python3
# cleanup_stale.py - 清理过时事件
"""
1. 删除 published_at 早于7天前的事件（除非是Tier 5里程碑事件）
2. 删除 published_at 为空且 discovered_at 早于3天的事件
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn
from fetch_news import extract_date_from_url


def cleanup(max_age_days: int = 7):
    conn = get_conn()
    cur = conn.cursor()

    cutoff = (datetime.now() - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    cutoff_dt = datetime.fromisoformat(cutoff)

    # 0. URL中日期解析覆盖Tavily的索引日期
    n_url = 0
    cur.execute("SELECT id, url, published_at FROM news_events")
    for row in cur.fetchall():
        url_date = extract_date_from_url(row["url"] or "")
        if not url_date:
            continue
        if url_date != (row["published_at"] or ""):
            cur.execute("UPDATE news_events SET published_at=? WHERE id=?",
                        (url_date, row["id"]))
            n_url += 1

    # 1. 显式过时事件：全删（不保留 severity=5 例外）
    # 投资场景下"今日要闻"必须新鲜；历史里程碑应在 capex_quarterly 等结构化表里
    cur.execute("""
        DELETE FROM news_events
        WHERE published_at < ?
          AND published_at != ''
    """, (cutoff,))
    n1 = cur.rowcount

    # 2. published_at 为空的，删除 discovered_at 早于3天前的
    cutoff_disc = (datetime.now() - timedelta(days=3)).isoformat()
    cur.execute("""
        DELETE FROM news_events
        WHERE (published_at IS NULL OR published_at = '')
          AND discovered_at < ?
    """, (cutoff_disc,))
    n2 = cur.rowcount

    conn.commit()
    print(f"   updated {n_url} published_at fields from URL parsing")

    # 报告
    cur.execute("SELECT COUNT(*) FROM news_events")
    remaining = cur.fetchone()[0]
    print(f"✅ removed {n1} stale events (older than {max_age_days}d)")
    print(f"✅ removed {n2} no-date events (discovered >3d ago)")
    print(f"   {remaining} events remaining in DB")
    conn.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--max-age", type=int, default=7)
    args = p.parse_args()
    cleanup(args.max_age)
