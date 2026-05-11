#!/usr/bin/env python3
# scrape_openrouter.py - 爬取 OpenRouter rankings
"""
OpenRouter 没有官方 API，需爬 rankings 页面。
rankings 页面用 Next.js 渲染，初始数据嵌入在 __NEXT_DATA__ 中。

策略：
1. fetch https://openrouter.ai/rankings?view=week
2. 解析 <script id="__NEXT_DATA__">{...}</script>
3. 提取 props.pageProps.rankings
4. 写入 token_model_weekly
"""
import os
import re
import sys
import json
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

URL = "https://openrouter.ai/rankings?view=week"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# 推断模型国别
def infer_country(provider: str) -> str:
    cn_providers = {"minimax", "moonshot", "deepseek", "zhipu", "alibaba",
                    "qwen", "xiaomi", "mimo", "baidu", "tencent", "bytedance"}
    p = (provider or "").lower()
    if any(c in p for c in cn_providers):
        return "CN"
    return "US"


def parse_next_data(html: str) -> dict:
    """从 HTML 中提取 __NEXT_DATA__ JSON"""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
                  html, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def fetch_rankings():
    proxies = {}
    if os.environ.get("HTTPS_PROXY"):
        proxies = {
            "http": os.environ["HTTP_PROXY"],
            "https": os.environ["HTTPS_PROXY"],
        }
    try:
        r = requests.get(URL, headers=HEADERS, proxies=proxies, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"⚠ fetch failed: {e}")
        return ""


def parse_rankings_from_html(html: str) -> list:
    """从HTML尝试多种方式抽取rankings数据"""
    # 方式1: __NEXT_DATA__
    nd = parse_next_data(html)
    if nd:
        try:
            pp = nd.get("props", {}).get("pageProps", {})
            for key in ["rankings", "models", "modelStats"]:
                if key in pp and isinstance(pp[key], list):
                    return pp[key]
        except Exception:
            pass

    # 方式2: 寻找内嵌的 JSON-LD 或自定义 <script type="application/json">
    for m in re.finditer(r'<script type="application/json"[^>]*>(.+?)</script>',
                         html, re.DOTALL):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list) and data and isinstance(data[0], dict):
                if any("token" in str(k).lower() or "rank" in str(k).lower()
                       for k in data[0].keys()):
                    return data
        except Exception:
            continue

    return []


def normalize_record(rec: dict) -> dict:
    """统一字段名"""
    # 尽量从多种可能字段名中提取
    name = rec.get("name") or rec.get("model") or rec.get("modelId") or ""
    provider = rec.get("provider") or rec.get("author") or ""
    tokens = (rec.get("tokens") or rec.get("totalTokens") or
              rec.get("tokenCount") or rec.get("usage", {}).get("totalTokens") or 0)
    rank = rec.get("rank") or rec.get("position") or 0
    # tokens to trillion
    if tokens > 1e6:
        tokens_t = round(tokens / 1e12, 3)
    else:
        tokens_t = float(tokens)
    return {
        "name": name,
        "provider": provider,
        "tokens_trillion": tokens_t,
        "rank": rank,
    }


def save_to_db(records: list):
    """保存到 token_model_weekly"""
    if not records:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    # 用本周一作为 week_start
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    week_start = monday.strftime("%Y-%m-%d")

    n = 0
    for i, rec in enumerate(records[:10], 1):
        norm = normalize_record(rec)
        if not norm["name"]:
            continue
        model_id = norm["name"].lower().replace(" ", "-").replace("/", "-")[:50]
        country = infer_country(norm["provider"])
        cur.execute("""
            INSERT OR REPLACE INTO token_model_weekly
            (model_id, model_name, provider, country, week_start,
             rank, tokens_trillion, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (model_id, norm["name"], norm["provider"], country, week_start,
              norm["rank"] or i, norm["tokens_trillion"], "OpenRouter scraped"))
        n += 1
    conn.commit()
    conn.close()
    return n


def main():
    print(f"🌐 fetching {URL}")
    html = fetch_rankings()
    if not html:
        print("⚠ no HTML received")
        return
    print(f"  received {len(html):,} bytes")

    records = parse_rankings_from_html(html)
    if not records:
        print("⚠ no rankings data found in HTML (page structure may have changed)")
        print("  fallback: keeping existing data unchanged")
        return

    print(f"  parsed {len(records)} model records")
    n = save_to_db(records)
    print(f"✅ saved {n} model entries for this week")


if __name__ == "__main__":
    main()
