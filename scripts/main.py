#!/usr/bin/env python3
# main.py - 主调度器
"""
每日执行流程:
1. 抓取新闻 (Tavily) → 去重入库
2. 更新资产价格 (yfinance)
3. 渲染HTML Dashboard
4. 部署到GitHub Pages
5. 事件驱动推送飞书

特殊调度:
- 周日: 强制推送周度汇总 (即使无新事件)
- 每月1日: 推送月度深度报告
"""
import os
import sys
import logging
import argparse
import subprocess
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import init_db, get_conn
import fetch_news
import render_html
import feishu_notifier

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def setup_logging():
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ]
    )


def update_asset_prices_today():
    """更新最近一周资产价格"""
    try:
        import yfinance as yf
        import time
        from datetime import timedelta
    except ImportError:
        logging.warning("yfinance not available, skip price update")
        return
    conn = get_conn()
    cur = conn.cursor()
    tickers = ["NVDA", "TSM", "AVGO", "MU", "ASML", "AMAT", "VRT", "CEG", "VST", "ANET", "CRWV"]
    end = datetime.now()
    start = end - timedelta(days=10)
    n = 0
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            hist = tk.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                              interval="1d", auto_adjust=False)
            if hist.empty:
                continue
            for idx, row in hist.iterrows():
                d = idx.strftime("%Y-%m-%d")
                close = float(row["Close"])
                vol = int(row["Volume"]) if not str(row["Volume"]) == "nan" else 0
                cur.execute("""
                    INSERT OR REPLACE INTO asset_prices
                    (ticker, date, close, volume)
                    VALUES (?, ?, ?, ?)
                """, (t, d, round(close, 2), vol))
                n += 1
            time.sleep(0.3)
        except Exception as e:
            logging.warning(f"price update {t} failed: {e}")
    conn.commit()
    conn.close()
    logging.info(f"updated {n} asset price rows")


def deploy_to_github():
    """推送 docs/ 到 GitHub Pages"""
    proj_root = Path(__file__).parent.parent
    docs = proj_root / "docs"
    if not docs.exists():
        logging.warning("docs/ not found, skip deploy")
        return
    try:
        cwd = str(proj_root)
        # 检测是否是git repo
        result = subprocess.run(["git", "rev-parse", "--git-dir"],
                                cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            logging.info("not a git repo yet, run setup_git first")
            return

        subprocess.run(["git", "add", "docs/"], cwd=cwd, check=False)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"],
                                cwd=cwd, capture_output=True)
        if result.returncode == 0:
            logging.info("no changes to commit")
            return

        msg = f"chore: daily update {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", msg], cwd=cwd, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=cwd, check=True, timeout=60)
        logging.info("✅ deployed to GitHub Pages")
    except subprocess.TimeoutExpired:
        logging.error("git push timeout")
    except Exception as e:
        logging.error(f"deploy failed: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true", help="跳过新闻抓取")
    parser.add_argument("--skip-deploy", action="store_true", help="跳过GitHub部署")
    parser.add_argument("--skip-notify", action="store_true", help="跳过飞书推送")
    parser.add_argument("--days", type=int, default=2, help="新闻抓取天数")
    parser.add_argument("--force-weekly", action="store_true", help="强制推送周度汇总")
    args = parser.parse_args()

    setup_logging()
    logging.info("=" * 60)
    logging.info("🚀 AI Infra Monitor - Daily Run")
    logging.info("=" * 60)

    # 1. 确保DB存在
    init_db()

    # 2. 抓取新闻
    new_events = 0
    if not args.skip_fetch:
        logging.info("📰 Step 1: fetching news...")
        try:
            new_events = fetch_news.fetch_all_news(days=args.days)
        except Exception as e:
            logging.error(f"news fetch failed: {e}")
    else:
        logging.info("⏭ skipping news fetch")

    # 3. 更新资产价格
    logging.info("💹 Step 2: updating asset prices...")
    try:
        update_asset_prices_today()
    except Exception as e:
        logging.error(f"asset update failed: {e}")

    # 4. 渲染HTML
    logging.info("🎨 Step 3: rendering HTML...")
    try:
        render_html.main()
    except Exception as e:
        logging.error(f"render failed: {e}")

    # 5. 部署
    if not args.skip_deploy:
        logging.info("🚢 Step 4: deploying to GitHub Pages...")
        deploy_to_github()
    else:
        logging.info("⏭ skipping deploy")

    # 6. 推送
    if not args.skip_notify:
        weekday = datetime.now().weekday()
        # 周日（=6）或强制
        if weekday == 6 or args.force_weekly:
            logging.info("📨 Step 5: weekly summary (Sunday)")
            feishu_notifier.notify_weekly()
        if new_events > 0:
            logging.info(f"📨 Step 5b: event-driven push ({new_events} new)")
            feishu_notifier.notify_if_events(min_severity=3)
        elif weekday != 6:
            logging.info("ℹ️ no new events, no weekly day, silent")
    else:
        logging.info("⏭ skipping notify")

    logging.info("✅ daily run complete")


if __name__ == "__main__":
    main()
