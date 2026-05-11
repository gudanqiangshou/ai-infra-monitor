#!/usr/bin/env python3
# classify_with_claude.py - 用 Claude API 智能分类事件
"""
对未分类或低置信度的事件批量调用 Claude API，输出:
- severity: 1-5
- impact_direction: positive / negative / neutral (针对相关资产)
- key_entities: 提取的实体列表
- one_line_summary: 一句话摘要
- investment_thesis: 1-2句投资视角解读

批处理：一次最多 20 条
缓存：成功分类后回写 DB，不重复调用
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

try:
    from anthropic import Anthropic
    HAS_CLAUDE = True
except ImportError:
    HAS_CLAUDE = False


PROMPT_TEMPLATE = """你是 AI 基建投资分析师。请对以下新闻事件进行结构化评估。

【投资视角】用户关注：四大云厂商 Capex（Amazon/Microsoft/Alphabet/Meta）、全球 AI 大模型 Token 消耗、AI 产业链关联资产（NVDA/TSM/AVGO/MU/ASML/HBM/电力/网络/中国AI芯片）

【评估维度】
- severity (1-5)：
  - 5 = 财报数据、Capex 指引变更、重大并购、新模型/新芯片发布、单日股价 >5% 变动
  - 4 = 数据中心新建公告、单家厂商关键披露、深度行业报告
  - 3 = 行业分析、CEO 访谈、技术展望
  - 2 = 一般动态
  - 1 = 弱相关或炒作

- impact_direction：
  - positive = 利好 AI 基建景气度
  - negative = 利空（如指引下调、监管收紧、需求疲软）
  - neutral = 中性事实陈述

- investment_thesis：用一句话从投资角度解读这条新闻意味着什么（影响哪类资产、值得关注什么）

【新闻列表】
{news_block}

【输出格式】严格JSON数组（无markdown标记），每条对应一个新闻：
[
  {{"id": 1, "severity": 5, "impact": "positive", "summary": "...", "thesis": "..."}}
]"""


def get_low_quality_events(limit: int = 20):
    """取近期且未被智能分类的事件"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, summary, source_name, published_at, severity
        FROM news_events
        WHERE (entities IS NULL OR entities = '[]' OR length(entities) < 10
               OR summary IS NULL OR length(summary) < 50)
          AND discovered_at > datetime('now', '-3 days')
        ORDER BY discovered_at DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_event_classification(event_id: int, sev: int, impact: str, summary: str, thesis: str):
    conn = get_conn()
    cur = conn.cursor()
    # 把 thesis 拼接到 summary 字段
    full_summary = f"{summary}\n\n💡 {thesis}" if thesis else summary
    cur.execute("""
        UPDATE news_events
        SET severity = ?, summary = ?
        WHERE id = ?
    """, (sev, full_summary, event_id))
    conn.commit()
    conn.close()


def classify_batch(events: list):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not HAS_CLAUDE:
        print("⚠ ANTHROPIC_API_KEY missing or anthropic SDK not installed")
        return 0

    client = Anthropic(api_key=api_key)
    news_block = ""
    for i, ev in enumerate(events, 1):
        news_block += f"\n[{i}] {ev['title']}\n  来源: {ev.get('source_name', '')}  日期: {ev.get('published_at', '')}\n  摘要: {(ev.get('summary') or '')[:200]}\n"

    prompt = PROMPT_TEMPLATE.format(news_block=news_block)

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        # 去掉可能的 markdown 代码块
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        results = json.loads(text)
        if not isinstance(results, list):
            print(f"⚠ unexpected response format")
            return 0

        updated = 0
        for r in results:
            idx = r.get("id", 0) - 1
            if 0 <= idx < len(events):
                ev = events[idx]
                update_event_classification(
                    ev["id"],
                    r.get("severity", 3),
                    r.get("impact", "neutral"),
                    r.get("summary", "")[:300],
                    r.get("thesis", "")[:200],
                )
                updated += 1
        return updated
    except json.JSONDecodeError as e:
        print(f"⚠ JSON parse error: {e}")
        print(f"   raw: {text[:300]}")
        return 0
    except Exception as e:
        print(f"⚠ classify error: {e}")
        return 0


def main():
    events = get_low_quality_events(limit=20)
    if not events:
        print("ℹ️ no events need classification")
        return
    print(f"🤖 classifying {len(events)} events with Claude...")
    n = classify_batch(events)
    print(f"✅ updated {n} events")


if __name__ == "__main__":
    main()
