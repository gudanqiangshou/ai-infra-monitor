#!/usr/bin/env python3
# backfill_token.py - 回填全球AI Token消耗历史数据
"""
两个维度的数据:
1. token_monthly: 平台级月度消耗 (Google/OpenAI/豆包/通义/Microsoft等)
2. token_model_weekly: OpenRouter Top10模型周度数据

单位: 万亿Token (Trillion T)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

# ======================================================================
# 平台级月度Token消耗 (单位: 万亿T/月)
# (platform, year, month, tokens_T, daily_avg_T, source, notes)
# ======================================================================
PLATFORM_MONTHLY = [
    # ---------- Google Gemini ----------
    ("gemini", 2024, 5, 9.7, 0.32, "Google I/O 2024", "首次披露月度Token"),
    ("gemini", 2025, 4, 480.0, 16.0, "Google I/O 2025", "Apr 2025披露"),
    ("gemini", 2025, 5, 600.0, 19.4, "估算", "线性插值"),
    ("gemini", 2025, 6, 800.0, 26.7, "估算", "线性插值"),
    ("gemini", 2025, 7, 980.0, 31.6, "Q2 2025 earnings call", "Jul披露"),
    ("gemini", 2025, 8, 1050.0, 33.9, "估算", ""),
    ("gemini", 2025, 9, 1150.0, 38.3, "估算", ""),
    ("gemini", 2025, 10, 1300.0, 41.9, "Q3 2025 earnings", "Oct披露"),
    ("gemini", 2025, 11, 1450.0, 48.3, "估算", ""),
    ("gemini", 2025, 12, 1600.0, 51.6, "估算", ""),
    ("gemini", 2026, 1, 1800.0, 58.1, "估算", ""),
    ("gemini", 2026, 2, 2000.0, 71.4, "估算", ""),
    ("gemini", 2026, 3, 2200.0, 71.0, "估算", ""),
    ("gemini", 2026, 4, 2400.0, 80.0, "Q1 2026 earnings", "持续增长"),

    # ---------- OpenAI GPT ----------
    ("gpt", 2025, 10, 258.0, 8.6, "OpenAI DevDay 2025", "Sam Altman披露日均8.6T"),
    ("gpt", 2025, 11, 320.0, 10.7, "估算", ""),
    ("gpt", 2025, 12, 400.0, 12.9, "估算", ""),
    ("gpt", 2026, 1, 480.0, 15.5, "估算", ""),
    ("gpt", 2026, 2, 540.0, 19.3, "估算", ""),
    ("gpt", 2026, 3, 648.0, 21.6, "OpenAI 2026 update", "15B tokens/min披露"),
    ("gpt", 2026, 4, 720.0, 24.0, "估算", ""),

    # ---------- ByteDance 豆包 ----------
    ("doubao", 2024, 5, 3.6, 0.12, "字节披露", "首次披露日均1200亿"),
    ("doubao", 2025, 10, 1200.0, 40.0, "火山引擎FORCE大会", ""),
    ("doubao", 2025, 11, 1400.0, 46.7, "估算", ""),
    ("doubao", 2025, 12, 1890.0, 63.0, "火山引擎披露", "日均63万亿"),
    ("doubao", 2026, 1, 2100.0, 67.7, "估算", ""),
    ("doubao", 2026, 2, 2700.0, 96.4, "估算", ""),
    ("doubao", 2026, 3, 3600.0, 120.0, "火山引擎披露", "日均120万亿"),
    ("doubao", 2026, 4, 3900.0, 130.0, "估算", "持续增长"),

    # ---------- Alibaba 通义千问 ----------
    ("qwen", 2025, 6, 60.0, 2.0, "阿里云栖大会", ""),
    ("qwen", 2025, 12, 150.0, 5.0, "阿里财报指引", "日均5T"),
    ("qwen", 2026, 1, 180.0, 6.0, "估算", ""),
    ("qwen", 2026, 2, 240.0, 8.6, "估算", ""),
    ("qwen", 2026, 3, 300.0, 10.0, "阿里巴巴Q3 FY26", ""),
    ("qwen", 2026, 4, 450.0, 15.0, "阿里2026目标", "目标15-20T/日"),

    # ---------- Microsoft Foundry ----------
    ("microsoft_foundry", 2025, 6, 100.0, 3.3, "Microsoft Build 2025", "H1 2025共500T"),
    ("microsoft_foundry", 2025, 12, 150.0, 4.8, "估算", ""),
    ("microsoft_foundry", 2026, 3, 200.0, 6.5, "估算", ""),

    # ---------- 中国全行业汇总 ----------
    ("china_total", 2024, 1, 0.1, 0.003, "国家数据局", "1000亿/日"),
    ("china_total", 2025, 6, 900.0, 30.0, "国家数据局", "30T/日"),
    ("china_total", 2025, 12, 3000.0, 100.0, "国家数据局", "100T/日"),
    ("china_total", 2026, 2, 5400.0, 180.0, "国家数据局", "180T/日"),
    ("china_total", 2026, 3, 4340.0, 140.0, "工信部", "140T/日"),
    ("china_total", 2026, 4, 4650.0, 155.0, "估算", ""),

    # ---------- OpenRouter 平台 (作为参照) ----------
    ("openrouter", 2024, 10, 0.04, 0.001, "OpenRouter公开数据", ""),
    ("openrouter", 2025, 4, 20.0, 0.67, "OpenRouter披露", "5T/周"),
    ("openrouter", 2025, 12, 12.0, 0.4, "OpenRouter", "3T/周"),
    ("openrouter", 2026, 1, 25.0, 0.83, "OpenRouter", ""),
    ("openrouter", 2026, 2, 56.0, 2.0, "OpenRouter", "14T/周"),
    ("openrouter", 2026, 3, 65.0, 2.1, "OpenRouter", "16T/周"),
    ("openrouter", 2026, 4, 80.0, 2.7, "OpenRouter", "20T/周"),
]

# ======================================================================
# OpenRouter Top 10 模型周度Token (单位: 万亿T/周)
# (model_id, model_name, provider, country, week_start, rank, tokens_T)
# ======================================================================
MODEL_WEEKLY = [
    # ---------- 2026年2月第2周 (峰值时期) ----------
    ("minimax-m25", "MiniMax M2.5", "MiniMax", "CN", "2026-02-09", 1, 4.55),
    ("kimi-k25", "Kimi K2.5", "Moonshot", "CN", "2026-02-09", 2, 4.02),
    ("glm-5", "GLM-5", "Zhipu", "CN", "2026-02-09", 3, 1.20),
    ("deepseek-v32", "DeepSeek V3.2", "DeepSeek", "CN", "2026-02-09", 4, 1.10),
    ("claude-sonnet-46", "Claude Sonnet 4.6", "Anthropic", "US", "2026-02-09", 5, 1.50),
    ("gpt-54", "GPT-5.4", "OpenAI", "US", "2026-02-09", 6, 1.05),
    ("claude-opus-46", "Claude Opus 4.6", "Anthropic", "US", "2026-02-09", 7, 0.80),
    ("gemini-31-pro", "Gemini 3.1 Pro", "Google", "US", "2026-02-09", 8, 0.60),
    ("qwen-3-max", "Qwen 3 Max", "Alibaba", "CN", "2026-02-09", 9, 0.50),
    ("gemini-31-flash", "Gemini 3.1 Flash Lite", "Google", "US", "2026-02-09", 10, 0.40),

    # ---------- 2026年3月第3周 ----------
    ("minimax-m25", "MiniMax M2.5", "MiniMax", "CN", "2026-03-16", 2, 2.50),
    ("kimi-k25", "Kimi K2.5", "Moonshot", "CN", "2026-03-16", 5, 1.00),
    ("deepseek-v32", "DeepSeek V3.2", "DeepSeek", "CN", "2026-03-16", 4, 1.20),
    ("claude-sonnet-46", "Claude Sonnet 4.6", "Anthropic", "US", "2026-03-16", 1, 2.10),
    ("gpt-54", "GPT-5.4", "OpenAI", "US", "2026-03-16", 3, 1.05),
    ("claude-opus-46", "Claude Opus 4.6", "Anthropic", "US", "2026-03-16", 6, 0.90),
    ("gemini-31-pro", "Gemini 3.1 Pro", "Google", "US", "2026-03-16", 7, 0.80),
    ("mimo-v2-pro", "MiMo-V2-Pro", "Xiaomi", "CN", "2026-03-16", 8, 3.80),
    ("gemini-31-flash", "Gemini 3.1 Flash Lite", "Google", "US", "2026-03-16", 10, 0.50),
    ("glm-5", "GLM-5", "Zhipu", "CN", "2026-03-16", 9, 0.70),

    # ---------- 2026年4月第2周 (最新) ----------
    ("mimo-v2-pro", "MiMo-V2-Pro", "Xiaomi", "CN", "2026-04-13", 1, 4.65),
    ("claude-sonnet-46", "Claude Sonnet 4.6", "Anthropic", "US", "2026-04-13", 2, 2.18),
    ("minimax-m27", "MiniMax M2.7", "MiniMax", "CN", "2026-04-13", 3, 1.92),
    ("deepseek-v32", "DeepSeek V3.2", "DeepSeek", "CN", "2026-04-13", 4, 1.22),
    ("qwen-36-plus", "Qwen 3.6 Plus", "Alibaba", "CN", "2026-04-13", 5, 1.10),
    ("claude-opus-46", "Claude Opus 4.6", "Anthropic", "US", "2026-04-13", 6, 1.01),
    ("gpt-54", "GPT-5.4", "OpenAI", "US", "2026-04-13", 7, 0.98),
    ("gemini-31-pro", "Gemini 3.1 Pro", "Google", "US", "2026-04-13", 8, 0.87),
    ("kimi-k2", "Kimi K2", "Moonshot", "CN", "2026-04-13", 9, 0.74),
    ("gemini-31-flash", "Gemini 3.1 Flash Lite", "Google", "US", "2026-04-13", 10, 0.68),
]


def backfill():
    conn = get_conn()
    cur = conn.cursor()

    p_inserted = 0
    for row in PLATFORM_MONTHLY:
        platform, year, month, tokens, daily, src, notes = row
        cur.execute("""
            INSERT OR REPLACE INTO token_monthly
            (platform, year, month, tokens_trillion, daily_avg_trillion, source, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (platform, year, month, tokens, daily, src, notes))
        p_inserted += 1

    m_inserted = 0
    for row in MODEL_WEEKLY:
        model_id, name, provider, country, week_start, rank, tokens = row
        cur.execute("""
            INSERT OR REPLACE INTO token_model_weekly
            (model_id, model_name, provider, country, week_start, rank, tokens_trillion, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (model_id, name, provider, country, week_start, rank, tokens, "OpenRouter"))
        m_inserted += 1

    conn.commit()
    conn.close()
    print(f"✅ Inserted {p_inserted} platform monthly rows, {m_inserted} model weekly rows")


if __name__ == "__main__":
    backfill()
