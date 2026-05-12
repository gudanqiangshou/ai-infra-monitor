#!/usr/bin/env python3
# db.py - SQLite 数据库管理
"""
存储:
- capex_quarterly: 季度Capex数据
- capex_guidance: 全年Capex指引（含变更历史）
- token_monthly: 月度Token消耗（平台级）
- token_model_weekly: 模型级周度Token（OpenRouter）
- news_events: 去重后的事件库
- asset_prices: 投资关联资产价格
- asset_events: 关联资产关键事件
"""
import sqlite3
import os
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "ai_infra.db"


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
    -- 季度Capex
    CREATE TABLE IF NOT EXISTS capex_quarterly (
        company TEXT NOT NULL,
        fiscal_year INTEGER NOT NULL,
        fiscal_quarter INTEGER NOT NULL,
        calendar_year INTEGER NOT NULL,
        calendar_quarter INTEGER NOT NULL,
        capex_billion_usd REAL NOT NULL,
        yoy_growth REAL,
        revenue_billion_usd REAL,
        operating_cashflow_billion_usd REAL,
        source TEXT,
        reported_at TEXT,
        notes TEXT,
        PRIMARY KEY (company, calendar_year, calendar_quarter)
    );

    -- Capex全年指引（含历史修订）
    CREATE TABLE IF NOT EXISTS capex_guidance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        guidance_year INTEGER NOT NULL,
        guidance_low_billion REAL,
        guidance_high_billion REAL,
        guidance_point_billion REAL,
        announced_date TEXT NOT NULL,
        source TEXT,
        notes TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_guidance_company_year
        ON capex_guidance(company, guidance_year);

    -- 月度Token (平台级)
    CREATE TABLE IF NOT EXISTS token_monthly (
        platform TEXT NOT NULL,
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        tokens_trillion REAL NOT NULL,
        daily_avg_trillion REAL,
        source TEXT,
        notes TEXT,
        PRIMARY KEY (platform, year, month)
    );

    -- OpenRouter周度模型排名
    CREATE TABLE IF NOT EXISTS token_model_weekly (
        model_id TEXT NOT NULL,
        model_name TEXT NOT NULL,
        provider TEXT,
        country TEXT,
        week_start TEXT NOT NULL,
        rank INTEGER,
        tokens_trillion REAL NOT NULL,
        change_pct REAL,
        source TEXT,
        PRIMARY KEY (model_id, week_start)
    );

    -- 事件库（去重）
    CREATE TABLE IF NOT EXISTS news_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_hash TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL,  -- capex | token | model_release | datacenter | investment
        subcategory TEXT,
        title TEXT NOT NULL,
        translated_title TEXT,   -- Claude-API 翻译后的中文标题
        summary TEXT,
        url TEXT,
        source_name TEXT,
        published_at TEXT,           -- ISO YYYY-MM-DD (规范化后)
        discovered_at TEXT NOT NULL,
        severity INTEGER DEFAULT 3,
        entities TEXT,               -- JSON: ["AMZN", "NVDA", ...]
        impact TEXT,                 -- positive / negative / neutral
        thesis TEXT,                 -- 投资视角解读 1-2句
        content_freshness TEXT,      -- recent / older / uncertain (Claude判定)
        extracted_date TEXT,         -- Claude从内容提取的真实事件日期
        extracted_data TEXT,         -- Claude提取的结构化数据 JSON
        date_source TEXT DEFAULT 'unknown',  -- url / tavily / unknown
        pushed BOOLEAN DEFAULT 0,
        pushed_at TEXT
    );

    -- Capex 指引变更待审核队列
    CREATE TABLE IF NOT EXISTS capex_guidance_pending (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER REFERENCES news_events(id),
        company TEXT NOT NULL,
        year INTEGER NOT NULL,
        new_low REAL,
        new_high REAL,
        confidence TEXT,
        source TEXT,
        detected_at TEXT,
        status TEXT DEFAULT 'pending',
        UNIQUE(event_id, company, year)
    );
    CREATE INDEX IF NOT EXISTS idx_events_discovered ON news_events(discovered_at DESC);
    CREATE INDEX IF NOT EXISTS idx_events_category ON news_events(category, discovered_at DESC);
    CREATE INDEX IF NOT EXISTS idx_events_severity ON news_events(severity, discovered_at DESC);

    -- 投资关联资产价格
    CREATE TABLE IF NOT EXISTS asset_prices (
        ticker TEXT NOT NULL,
        date TEXT NOT NULL,
        close REAL,
        change_pct REAL,
        volume INTEGER,
        market_cap_billion REAL,
        PRIMARY KEY (ticker, date)
    );

    -- 投资关联事件
    CREATE TABLE IF NOT EXISTS asset_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_hash TEXT UNIQUE NOT NULL,
        ticker TEXT,
        category TEXT,  -- earnings | guidance | product | macro
        title TEXT NOT NULL,
        summary TEXT,
        url TEXT,
        impact TEXT,    -- positive | negative | neutral
        magnitude INTEGER, -- 1-5
        published_at TEXT,
        discovered_at TEXT NOT NULL
    );

    -- 系统状态/最后扫描时间
    CREATE TABLE IF NOT EXISTS scan_state (
        scan_type TEXT PRIMARY KEY,
        last_scan_at TEXT,
        last_success_at TEXT,
        meta TEXT
    );
    """)

    # 幂等迁移：旧 DB 缺列时补齐（不丢数据）
    _ensure_columns(cur)

    conn.commit()
    conn.close()
    print(f"✅ Database initialized at {DB_PATH}")


def _ensure_columns(cur):
    """对历史 DB 幂等加列，应对 schema 演进"""
    cur.execute("PRAGMA table_info(news_events)")
    existing = {r[1] for r in cur.fetchall()}
    migrations = [
        ("translated_title", "TEXT"),
        ("content_freshness", "TEXT"),
        ("extracted_date", "TEXT"),
        ("extracted_data", "TEXT"),
        ("date_source", "TEXT DEFAULT 'unknown'"),
        ("impact", "TEXT"),
        ("thesis", "TEXT"),
    ]
    for col, dtype in migrations:
        if col not in existing:
            cur.execute(f"ALTER TABLE news_events ADD COLUMN {col} {dtype}")
            print(f"  + migrated: news_events.{col}")


if __name__ == "__main__":
    init_db()
