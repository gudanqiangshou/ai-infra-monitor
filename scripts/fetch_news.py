#!/usr/bin/env python3
# fetch_news.py - 通过 Tavily 抓取每日新闻
"""
分类抓取:
1. Capex 相关 (财报、指引变更、数据中心新建)
2. Token 相关 (模型发布、调用量披露、价格战)
3. 投资关联 (NVDA订单、TSM营收、HBM出货、电力)
"""
import os
import re
import json
import hashlib
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

# URL 中的日期模式（按可信度排序）
URL_DATE_PATTERNS = [
    re.compile(r"/(\d{4})/(\d{2})(\d{2})/"),        # /2026/0408/
    re.compile(r"/(\d{4})-(\d{2})-(\d{2})/"),       # /2026-04-08/
    re.compile(r"/(\d{4})/(\d{2})/(\d{2})/"),       # /2026/04/08/
    re.compile(r"/(\d{4})(\d{2})(\d{2})_"),         # /20260408_
    re.compile(r"-(\d{4})-(\d{2})-(\d{2})\."),      # -2026-04-08.html
]


def extract_date_from_url(url: str) -> str:
    """从URL中提取日期，找不到返回空字符串"""
    if not url:
        return ""
    for pat in URL_DATE_PATTERNS:
        m = pat.search(url)
        if m:
            try:
                y, mo, d = m.groups()
                # 合理性检查
                if 2020 <= int(y) <= 2030 and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
                    return f"{y}-{mo}-{d}"
            except Exception:
                continue
    return ""

try:
    from tavily import TavilyClient
    HAS_TAVILY = True
except ImportError:
    HAS_TAVILY = False
    print("⚠ tavily not installed")


# ======================================================================
# 搜索查询模板 (按类别)
# ======================================================================
CAPEX_QUERIES = [
    "Amazon AWS capex capital expenditure 2026 quarterly earnings billion",
    "Microsoft Azure capex 2026 AI infrastructure investment billion",
    "Alphabet Google capex 2026 cloud guidance billion data center",
    "Meta capital expenditure 2026 AI infrastructure billion guidance",
    "hyperscaler capex 2026 AI infrastructure data center billion",
    "亚马逊 微软 谷歌 Meta 资本开支 2026 财报 AI",
]

TOKEN_QUERIES = [
    "OpenRouter top models token usage 2026 weekly ranking trillion",
    "豆包 通义千问 token 调用量 2026 日均 万亿",
    "DeepSeek Kimi MiniMax GLM model release 2026 token usage",
    "Gemini OpenAI GPT Claude token consumption 2026 monthly",
    "AI model API pricing 2026 token cost reduction",
    "global AI token consumption monthly 2026 trillion",
]

INVESTMENT_QUERIES = [
    "NVIDIA NVDA data center revenue 2026 quarterly earnings guidance",
    "TSMC monthly revenue 2026 AI chip CoWoS HBM",
    "SK Hynix Micron HBM 2026 quarterly shipment AI memory",
    "AI data center power electricity nuclear PPA 2026",
    "Korea semiconductor exports 2026 monthly AI",
    "Vertiv Arista Broadcom CoreWeave AI infrastructure 2026 earnings",
    "数据中心 电力 核电 AI 算力 2026 中国",
    "寒武纪 海光 浪潮 2026 AI 芯片 国产 财报",
]

# ======================================================================
# 域名权重（提升可信度高的来源）
# ======================================================================
DOMAIN_WEIGHTS = {
    "reuters.com": 1.0, "bloomberg.com": 1.0, "ft.com": 1.0, "wsj.com": 1.0,
    "cnbc.com": 0.95, "fortune.com": 0.9, "techcrunch.com": 0.85,
    "tomshardware.com": 0.85, "datacenterdynamics.com": 0.9,
    "openrouter.ai": 1.0, "a16z.com": 0.95,
    "wallstreetcn.com": 0.9, "caixin.com": 0.9, "yicai.com": 0.85,
    "36kr.com": 0.85, "qbitai.com": 0.8, "cls.cn": 0.85,
}


def normalize_url(url: str) -> str:
    """去除utm/ref参数"""
    if not url:
        return ""
    return url.split("?")[0].split("#")[0]


def event_hash(title: str, url: str) -> str:
    """事件哈希用于去重"""
    key = (title or "").lower().strip()[:120] + "|" + normalize_url(url or "")
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def is_duplicate(cur, h: str) -> bool:
    cur.execute("SELECT 1 FROM news_events WHERE event_hash=? LIMIT 1", (h,))
    return cur.fetchone() is not None


def search_tavily(client, query: str, days: int = 3, max_results: int = 5):
    """单次Tavily搜索"""
    try:
        resp = client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            days=days,
            include_answer=False,
        )
        return resp.get("results", []) or []
    except Exception as e:
        print(f"  ⚠ search failed: {e}")
        return []


def classify_category(query_idx: int, n_capex: int, n_token: int) -> str:
    """根据查询索引判断类别"""
    if query_idx < n_capex:
        return "capex"
    elif query_idx < n_capex + n_token:
        return "token"
    else:
        return "investment"


def extract_entities(title: str, content: str) -> list:
    """提取相关实体"""
    text = (title + " " + (content or "")).lower()
    entities = []
    keyword_map = {
        "AMZN": ["amazon", "aws", "亚马逊"],
        "MSFT": ["microsoft", "azure", "微软"],
        "GOOGL": ["google", "alphabet", "gemini", "谷歌"],
        "META": ["meta", "facebook", "instagram", "llama"],
        "NVDA": ["nvidia", "英伟达", "nvda"],
        "TSM": ["tsmc", "台积电"],
        "AVGO": ["broadcom", "博通"],
        "MU": ["micron", "美光"],
        "HYNIX": ["sk hynix", "海力士"],
        "ASML": ["asml", "阿斯麦"],
        "OPENAI": ["openai", "gpt", "chatgpt"],
        "ANTHROPIC": ["anthropic", "claude"],
        "BYTEDANCE": ["bytedance", "doubao", "字节", "豆包"],
        "ALIBABA": ["alibaba", "qwen", "通义", "阿里"],
        "DEEPSEEK": ["deepseek"],
        "MOONSHOT": ["kimi", "moonshot", "月之暗面"],
        "MINIMAX": ["minimax"],
        "XIAOMI": ["xiaomi", "mimo", "小米"],
        "ZHIPU": ["zhipu", "glm", "智谱"],
    }
    for ent, kws in keyword_map.items():
        if any(kw in text for kw in kws):
            entities.append(ent)
    return entities


def severity_score(title: str, content: str, category: str) -> int:
    """事件重要性 1-5"""
    text = (title + " " + (content or "")).lower()

    # Tier 5: 财报、指引变更、新模型发布
    if any(kw in text for kw in [
        "guidance", "raises", "lowered", "earnings report", "q1 2026", "q4 2025",
        "财报", "上调指引", "下调指引", "发布", "release", "launches",
        "announces $", "anuncia"
    ]):
        return 5

    # Tier 4: 数据中心新建、收购、单日重大新闻
    if any(kw in text for kw in [
        "data center", "acquires", "acquisition", "billion deal",
        "数据中心", "并购", "收购", "签约",
        "new model", "新模型"
    ]):
        return 4

    # Tier 3: 行业分析、技术发布
    if any(kw in text for kw in [
        "analysis", "report", "outlook", "forecast",
        "分析", "研报", "展望"
    ]):
        return 3

    return 2


def is_too_old(published: str, max_days: int = 7) -> bool:
    """硬过滤：超过 max_days 天的新闻丢弃（Tavily的days参数不可靠）"""
    if not published:
        return True  # 没有日期的也丢
    try:
        # 支持 "2026-04-08" 或 "2026-04-08T12:00:00"
        d = datetime.fromisoformat(published.split("T")[0])
        return (datetime.now() - d).days > max_days
    except Exception:
        return True


def fetch_all_news(days: int = 3, max_per_query: int = 5, max_age_days: int = 7):
    """主入口：执行所有搜索

    days: Tavily search 时间窗口
    max_age_days: 硬过滤上限（Tavily返回结果中超过此天数的丢弃）
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key or not HAS_TAVILY:
        print("⚠ TAVILY_API_KEY missing or tavily not installed - skipping fetch")
        return 0

    client = TavilyClient(api_key=api_key)
    conn = get_conn()
    cur = conn.cursor()

    all_queries = CAPEX_QUERIES + TOKEN_QUERIES + INVESTMENT_QUERIES
    new_count = 0
    dup_count = 0
    stale_count = 0

    for i, q in enumerate(all_queries):
        category = classify_category(i, len(CAPEX_QUERIES), len(TOKEN_QUERIES))
        print(f"[{i+1}/{len(all_queries)}] [{category}] {q[:60]}...")
        results = search_tavily(client, q, days=days, max_results=max_per_query)

        for r in results:
            title = r.get("title", "").strip()
            url = normalize_url(r.get("url", ""))
            content = r.get("content", "")[:500]
            tavily_pub = r.get("published_date") or ""

            if not title or not url:
                continue

            # 优先级：URL内日期 > Tavily published_date
            url_date = extract_date_from_url(url)
            published = url_date or tavily_pub

            # 如果URL有日期且早于Tavily日期，说明Tavily报告的是索引日期，以URL为准
            if url_date and tavily_pub:
                try:
                    url_d = datetime.fromisoformat(url_date)
                    tav_d = datetime.fromisoformat(tavily_pub.split("T")[0])
                    if url_d < tav_d:
                        published = url_date  # 用URL内的真实日期
                except Exception:
                    pass

            # 硬过滤：丢弃过时新闻
            if is_too_old(published, max_days=max_age_days):
                stale_count += 1
                continue

            h = event_hash(title, url)
            if is_duplicate(cur, h):
                dup_count += 1
                continue

            sev = severity_score(title, content, category)
            ents = extract_entities(title, content)
            domain = url.split("/")[2] if "://" in url else ""
            domain = domain.removeprefix("www.")

            cur.execute("""
                INSERT INTO news_events
                (event_hash, category, title, summary, url, source_name,
                 published_at, discovered_at, severity, entities)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (h, category, title, content, url, domain,
                  published, datetime.now().isoformat(), sev,
                  json.dumps(ents)))
            new_count += 1

        time.sleep(0.3)  # rate limit

    conn.commit()
    conn.close()
    print(f"\n✅ fetched: {new_count} new events, {dup_count} duplicates, {stale_count} stale (>{max_age_days}d)")
    return new_count


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--max", type=int, default=5)
    args = p.parse_args()
    fetch_all_news(days=args.days, max_per_query=args.max)
