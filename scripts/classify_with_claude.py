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


PROMPT_TEMPLATE = """你是 AI 基建投资分析师。对每条新闻输出结构化 JSON。

【用户投资视角】四大美国云（AMZN/MSFT/GOOGL/META）Capex、中国云（阿里/腾讯/字节/百度）、AI模型Token消耗、AI产业链（NVDA/TSM/AVGO/MU/HBM/电力/网络/中国AI芯片）

【今天日期】{today}

【输出字段】

1. **translated_title**：英文→中文简洁标题（30字内，保留Capex/AI/GPU缩写）。中文直接复制。

2. **severity** (1-5)：5=财报/指引变更/重大发布；4=数据中心新建/深度披露；3=行业分析/CEO访谈；2=一般；1=炒作

3. **impact**：positive / negative / neutral

4. **thesis**：投资视角解读（影响哪类资产），35字内

5. **content_freshness** (重要)：判断新闻所述事件**何时发生**
   - "recent" = 标题/摘要明确提到近期日期(7天内)，或讲的是正在发生的事
   - "older" = 标题/摘要提到具体的历史日期(>7天前)，或是历史回顾
   - "uncertain" = 无法判断
   保守原则：宁可判 uncertain 也不要错判 recent

6. **extracted_date** (可选)：若新闻明确提到事件日期，输出 ISO 格式 "YYYY-MM-DD" 或月份 "YYYY-MM"；找不到填 null

7. **extracted_data** (可选，仅当新闻明确报道 **新的全年Capex指引** 时使用)：
   {{"type": "capex_guidance", "company": "META", "year": 2026,
     "new_low": 125, "new_high": 145, "confidence": "high|medium|low"}}

   ⚠️ 严格区分 (重要！)：
   - ✅ 全年指引：必须是"全年/年度/full-year guidance"，金额通常 $50B-$300B 区间
     如 "Meta 上调全年指引至 $145B"，"AMZN guides 2026 capex to $200B"
   - ❌ 单季数字 (NOT guidance)：如 "AMZN Q1 Capex $44.2B"，"四巨头季度合计 $130B"
     这些是已发生的实际值，不是指引；填 null
   - ❌ 行业总额：如 "四大合计 $700B"、"全球 AI 支出 $2T"；填 null
   - ❌ 重复报道：标题/摘要里只是回顾已知指引，没有新数字变化；填 null

   confidence:
   - high：标题明确含动词(上调/raised/boosts)+具体数字+公司+年份
   - medium：暗示有变化但数字或公司不明确
   - low：模糊提及
   不确定就填 null，宁缺勿滥

【新闻列表】
{news_block}

【输出】严格JSON数组（无markdown），中文引号必须用「」或单引号，禁用英文双引号 "
[
  {{"id": 1, "translated_title": "...", "severity": 5, "impact": "positive", "thesis": "...",
    "content_freshness": "recent", "extracted_date": "2026-05-12",
    "extracted_data": {{"type": "capex_guidance", "company": "META", "year": 2026, "new_low": 125, "new_high": 145, "confidence": "high"}}}},
  {{"id": 2, "translated_title": "...", "severity": 3, "impact": "neutral", "thesis": "...",
    "content_freshness": "older", "extracted_date": "2025-02", "extracted_data": null}}
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


def update_event(event_id: int, translated_title: str, sev: int, impact: str,
                 thesis: str, freshness: str = "", extracted_date: str = "",
                 extracted_data: dict = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE news_events
        SET translated_title = ?, severity = ?, impact = ?, thesis = ?,
            content_freshness = ?, extracted_date = ?, extracted_data = ?
        WHERE id = ?
    """, (translated_title, sev, impact, thesis,
          freshness or "",
          extracted_date or "",
          json.dumps(extracted_data, ensure_ascii=False) if extracted_data else None,
          event_id))
    conn.commit()
    conn.close()


def auto_sync_guidance(event_id: int, ed: dict, ev_source: str = "",
                        freshness: str = "uncertain",
                        extracted_date: str = "",
                        date_source: str = "unknown",
                        published_at: str = ""):
    """高置信度的 Capex 指引变更自动写入 capex_guidance；中等放入 pending 待审

    Codex 门禁:
    - 必须 freshness == 'recent'
    - 必须有可信日期 (date_source != unknown 或 extracted_date 存在)
    - announced_date 用 extracted_date / published_at，不用今天
    """
    if not ed or ed.get("type") != "capex_guidance":
        return None

    # 门禁: 内容必须确认是近期的
    if freshness != "recent":
        # uncertain/older 一律不进主表，最多进 pending
        ed = dict(ed)
        ed["confidence"] = "low"  # 强制降级

    # 门禁: 必须有可信日期来源
    if date_source == "unknown" and not extracted_date:
        # 完全没有可信日期，丢弃
        return None
    company = ed.get("company", "").upper()
    if company not in ("AMZN", "AMAZON", "MSFT", "MICROSOFT", "GOOGL", "GOOGLE", "ALPHABET", "META"):
        return None
    # 规范化
    company = {"AMAZON": "AMZN", "MICROSOFT": "MSFT", "GOOGLE": "GOOGL", "ALPHABET": "GOOGL"}.get(company, company)
    year = ed.get("year")
    new_low = ed.get("new_low")
    new_high = ed.get("new_high")
    confidence = ed.get("confidence", "low")
    if not (year and (new_low or new_high)):
        return None
    # 默认: low只填一边时另一边相同
    new_low = new_low or new_high
    new_high = new_high or new_low

    conn = get_conn()
    cur = conn.cursor()
    from datetime import datetime as _dt
    # announced_date 优先用提取的真实日期，其次 published_at，最后才是今天（最不可靠）
    today = _dt.now().strftime("%Y-%m-%d")
    announce_date = extracted_date or published_at or today
    # 把 "YYYY-MM" 补成完整日期
    if announce_date and len(announce_date) == 7:
        announce_date = announce_date + "-15"

    if confidence == "high":
        # 健全性检查 1: 提取的数字应该是全年指引规模 (50B-300B 区间)
        # 季度Capex (~10-50B) 大概率是被误识别
        midpoint = (new_low + new_high) / 2
        if midpoint < 50 or midpoint > 300:
            # 太小或太大，可能是季度数据或错误，降级为 pending
            cur.execute("""
                INSERT OR IGNORE INTO capex_guidance_pending
                (event_id, company, year, new_low, new_high, confidence, source, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_id, company, year, new_low, new_high, f"suspicious-{confidence}",
                  f"{ev_source} (out of plausible range)", _dt.now().isoformat()))
            conn.commit()
            conn.close()
            return "pending"

        # 健全性检查 2: 与现有最新指引比较，若完全一致或差别<2%，跳过（重复）
        cur.execute("""
            SELECT guidance_low_billion, guidance_high_billion
            FROM capex_guidance
            WHERE company=? AND guidance_year=?
            ORDER BY announced_date DESC LIMIT 1
        """, (company, year))
        latest = cur.fetchone()
        if latest:
            latest_mid = (latest["guidance_low_billion"] + latest["guidance_high_billion"]) / 2
            if abs(midpoint - latest_mid) / max(latest_mid, 1) < 0.02:  # 差异<2%
                conn.close()
                return None  # 实质上是同一指引的复述

        # 健全性检查 3: 同日内不要重复插入
        cur.execute("""
            SELECT id FROM capex_guidance
            WHERE company=? AND guidance_year=? AND announced_date=?
              AND guidance_low_billion=? AND guidance_high_billion=?
        """, (company, year, today, new_low, new_high))
        if cur.fetchone():
            conn.close()
            return None

        # 写入主表
        cur.execute("""
            INSERT INTO capex_guidance
            (company, guidance_year, guidance_low_billion, guidance_high_billion,
             guidance_point_billion, announced_date, source, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (company, year, new_low, new_high, midpoint,
              announce_date, f"AI-extracted from event #{event_id}", ev_source))
        conn.commit()
        conn.close()
        return "applied"
    elif confidence == "medium":
        # 待审核队列
        cur.execute("""
            INSERT OR IGNORE INTO capex_guidance_pending
            (event_id, company, year, new_low, new_high, confidence, source, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, company, year, new_low, new_high, confidence,
              ev_source, _dt.now().isoformat()))
        conn.commit()
        conn.close()
        return "pending"
    conn.close()
    return None


def delete_stale_event(event_id: int):
    """删除被识别为过时的事件"""
    conn = get_conn()
    conn.execute("DELETE FROM news_events WHERE id = ?", (event_id,))
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

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = PROMPT_TEMPLATE.format(today=today, news_block=news_block)
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    try:
        # max_tokens 必须够大：每条≥120 tokens output (translated_title + thesis + JSON结构)
        # 15条/批 → 至少需要 2500 + 缓冲 = 4096 tokens
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
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

        # 兜底：尝试修复 Claude 偶尔输出的非法双引号
        # 替换形如 "abc"def"hij" 中间嵌的双引号为单引号
        # 简单启发式：每个 字段值 内若出现额外双引号，转单引号
        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            # 尝试用正则修复常见问题
            import re
            # 模式：在字段值字符串内部出现的双引号（非键字段边界）
            # 简化版：寻找 "..."xxx"..." 替换内部 " 为 '
            repaired = re.sub(
                r'("(?:translated_title|thesis)"\s*:\s*"[^"]*?)"([^"]*?)"([^"]*?")',
                r"\1'\2'\3",
                text,
                flags=re.DOTALL
            )
            results = json.loads(repaired)
        if not isinstance(results, list):
            print(f"⚠ unexpected format: {type(results)}")
            return 0

        updated = 0
        deleted = 0
        synced = 0
        pending = 0
        for r in results:
            idx = r.get("id", 0) - 1
            if 0 <= idx < len(events):
                ev = events[idx]
                freshness = r.get("content_freshness", "uncertain")
                ext_data = r.get("extracted_data")

                # 1. 先写入分类结果
                update_event(
                    ev["id"],
                    r.get("translated_title", "")[:200],
                    r.get("severity", 3),
                    r.get("impact", "neutral"),
                    r.get("thesis", "")[:200],
                    freshness=freshness,
                    extracted_date=r.get("extracted_date") or "",
                    extracted_data=ext_data,
                )
                updated += 1

                # 2. 内容确认是过时的 → 删除
                if freshness == "older":
                    delete_stale_event(ev["id"])
                    deleted += 1
                    continue

                # 3. 提取到 Capex 指引变更 → 走门禁
                if ext_data:
                    # 取数据库里最新的 date_source（fetch_news已写入）
                    conn_q = get_conn()
                    cur_q = conn_q.cursor()
                    cur_q.execute("SELECT date_source, published_at FROM news_events WHERE id=?", (ev["id"],))
                    row = cur_q.fetchone()
                    ds = row["date_source"] if row else "unknown"
                    pub = row["published_at"] if row else ""
                    conn_q.close()

                    result = auto_sync_guidance(
                        ev["id"], ext_data, ev.get("source_name", ""),
                        freshness=freshness,
                        extracted_date=r.get("extracted_date") or "",
                        date_source=ds or "unknown",
                        published_at=pub or "",
                    )
                    if result == "applied":
                        synced += 1
                    elif result == "pending":
                        pending += 1

        if deleted or synced or pending:
            print(f"   ↓ deleted {deleted} stale, applied {synced} guidance, queued {pending} pending")
        return updated
    except json.JSONDecodeError as e:
        import logging
        logging.error(f"classify JSON parse error: {e}")
        logging.error(f"raw response (first 500 chars): {text[:500]}")
        logging.error(f"raw response (last 200 chars): {text[-200:]}")
        return 0
    except Exception as e:
        import logging
        logging.error(f"classify API error: {e}")
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
