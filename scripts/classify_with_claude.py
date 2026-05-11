#!/usr/bin/env python3
# classify_with_claude.py - 用 Claude API 智能翻译+分类事件
"""
对未处理的事件批量调用 Claude API：
- translated_title: 中文翻译（核心 - 英文标题→中文）
- severity: 1-5
- impact: positive / negative / neutral
- thesis: 1句投资视角解读

批处理：一次最多 15 条（避免 token 超限）
缓存：写入 DB 后不重复调用
环境变量：
  ANTHROPIC_API_KEY  必填
  ANTHROPIC_BASE_URL 可选（AiCodeWith等中转）
  CLAUDE_MODEL       默认 claude-sonnet-4-6
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


PROMPT_TEMPLATE = """你是 AI 基建投资分析师。对以下新闻进行结构化处理。

【用户投资视角】关注：四大美国云（AMZN/MSFT/GOOGL/META）Capex、中国云（阿里/腾讯/字节/百度）、AI模型Token消耗、AI产业链（NVDA/TSM/AVGO/MU/HBM/电力/网络/中国AI芯片）

【处理任务】对每条新闻输出：
1. **translated_title**：把英文标题翻译为简洁中文（30字内，保留专业术语如 Capex、AI、GPU 等英文缩写）。中文标题直接复制原文。
2. **severity**（1-5）：
   - 5 = 财报数据、Capex指引变更、重大并购、新模型/新芯片发布、单日股价 >5% 波动
   - 4 = 数据中心新建、单家关键披露、深度行业研报
   - 3 = 行业分析、CEO访谈、技术展望
   - 2 = 一般动态
   - 1 = 弱相关/炒作
3. **impact**：positive（利好AI基建）/ negative（利空）/ neutral
4. **thesis**：一句话从投资视角解读（影响哪类资产、值得关注什么），35字内

【新闻列表】
{news_block}

【输出格式】严格JSON数组（无markdown，无解释文字），每条对应一个新闻：
[
  {{"id": 1, "translated_title": "...", "severity": 5, "impact": "positive", "thesis": "..."}},
  {{"id": 2, "translated_title": "...", "severity": 4, "impact": "neutral", "thesis": "..."}}
]"""


def get_unprocessed_events(limit: int = 15):
    """取需要翻译/分类的事件 - 翻译为空的优先"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, summary, source_name, published_at, severity, category
        FROM news_events
        WHERE (translated_title IS NULL OR translated_title = '')
        ORDER BY severity DESC, discovered_at DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_event(event_id: int, translated_title: str, sev: int, impact: str, thesis: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE news_events
        SET translated_title = ?, severity = ?, impact = ?, thesis = ?
        WHERE id = ?
    """, (translated_title, sev, impact, thesis, event_id))
    conn.commit()
    conn.close()


def create_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return Anthropic(**kwargs)


def classify_batch(events: list, client):
    if not events:
        return 0

    news_block = ""
    for i, ev in enumerate(events, 1):
        title = ev['title'][:200]
        summary = (ev.get('summary') or '')[:150]
        news_block += f"\n[{i}] {title}\n  来源:{ev.get('source_name', '')} 类别:{ev.get('category')} 摘要:{summary}\n"

    prompt = PROMPT_TEMPLATE.format(news_block=news_block)
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        # 去掉可能的 markdown 代码块
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        text = text.strip()

        # 寻找JSON数组的边界
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start:end+1]

        results = json.loads(text)
        if not isinstance(results, list):
            print(f"⚠ unexpected format: {type(results)}")
            return 0

        updated = 0
        for r in results:
            idx = r.get("id", 0) - 1
            if 0 <= idx < len(events):
                ev = events[idx]
                update_event(
                    ev["id"],
                    r.get("translated_title", "")[:200],
                    r.get("severity", 3),
                    r.get("impact", "neutral"),
                    r.get("thesis", "")[:200],
                )
                updated += 1
        return updated
    except json.JSONDecodeError as e:
        print(f"⚠ JSON parse error: {e}")
        print(f"   raw response: {text[:400]}")
        return 0
    except Exception as e:
        print(f"⚠ classify error: {e}")
        return 0


def main(batch_size: int = 15, max_batches: int = 20):
    if not HAS_CLAUDE:
        print("❌ anthropic SDK not installed")
        return

    client = create_client()
    if not client:
        print("❌ ANTHROPIC_API_KEY not set")
        return

    print(f"🤖 model: {os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-6')}")
    if os.environ.get("ANTHROPIC_BASE_URL"):
        print(f"   base: {os.environ['ANTHROPIC_BASE_URL']}")

    total_updated = 0
    for batch_idx in range(max_batches):
        events = get_unprocessed_events(limit=batch_size)
        if not events:
            print(f"ℹ️ no more events to process")
            break
        print(f"\n[batch {batch_idx+1}] processing {len(events)} events...")
        n = classify_batch(events, client)
        total_updated += n
        print(f"   updated {n}/{len(events)}")
        time.sleep(1)  # rate limit safety

    print(f"\n✅ total updated: {total_updated}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--batch-size", type=int, default=15)
    p.add_argument("--max-batches", type=int, default=20)
    args = p.parse_args()
    main(args.batch_size, args.max_batches)
