#!/usr/bin/env python3
# backfill_extras.py - 回填扩展指标
"""
1. 中国云厂商 Capex (阿里/腾讯/字节/百度)
2. TSMC 月度营收 (每月10日左右公布)
3. 韩国半导体出口数据 (每月1日公布)
4. AI 数据中心 vs BTC挖矿 电力消耗对比
"""
import sys
import sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn


def extend_schema():
    """新增扩展指标表"""
    conn = get_conn()
    conn.executescript("""
    -- 中国云厂商 Capex (季度，亿人民币)
    CREATE TABLE IF NOT EXISTS china_capex_quarterly (
        company TEXT NOT NULL,
        calendar_year INTEGER NOT NULL,
        calendar_quarter INTEGER NOT NULL,
        capex_billion_cny REAL NOT NULL,
        capex_billion_usd REAL,    -- 按6.5/6.8/7.0汇率换算
        source TEXT,
        notes TEXT,
        PRIMARY KEY (company, calendar_year, calendar_quarter)
    );

    -- TSMC 月度营收 (亿新台币 + 亿美元)
    CREATE TABLE IF NOT EXISTS tsmc_monthly (
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        revenue_billion_twd REAL NOT NULL,
        revenue_billion_usd REAL,
        yoy_pct REAL,
        mom_pct REAL,
        source TEXT,
        PRIMARY KEY (year, month)
    );

    -- 韩国半导体出口 (亿美元)
    CREATE TABLE IF NOT EXISTS korea_semi_exports (
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        exports_billion_usd REAL NOT NULL,
        memory_billion_usd REAL,
        yoy_pct REAL,
        source TEXT,
        PRIMARY KEY (year, month)
    );

    -- AI 数据中心 vs BTC挖矿电力 (TWh/年)
    CREATE TABLE IF NOT EXISTS power_competition (
        year INTEGER NOT NULL,
        category TEXT NOT NULL,  -- 'ai_datacenter' / 'btc_mining' / 'crypto_other'
        twh_per_year REAL NOT NULL,
        source TEXT,
        PRIMARY KEY (year, category)
    );
    """)
    conn.commit()
    conn.close()


# ======================================================================
# 中国四大云 Capex (季度，单位：十亿人民币 = CNY billions)
# 来源：上市公司10-Q财报 + Bloomberg/天风证券/华泰证券研报
# 注：阿里(FY错位 4月起算)、腾讯有公开数据；字节为研报估算
# ======================================================================
CHINA_CAPEX = [
    # company, year, quarter, capex_cny_bn, source
    # ---------- 2024 ----------
    ("Alibaba", 2024, 1, 11.6, "FY24Q4财报"),
    ("Alibaba", 2024, 2, 11.9, "FY25Q1财报"),
    ("Alibaba", 2024, 3, 17.5, "FY25Q2财报"),
    ("Alibaba", 2024, 4, 31.8, "FY25Q3财报"),
    ("Tencent", 2024, 1, 14.4, "财报"),
    ("Tencent", 2024, 2, 8.4, "财报"),
    ("Tencent", 2024, 3, 17.1, "财报"),
    ("Tencent", 2024, 4, 36.6, "财报"),
    ("ByteDance", 2024, 1, 20.0, "天风证券研报"),
    ("ByteDance", 2024, 2, 25.0, "天风证券研报"),
    ("ByteDance", 2024, 3, 35.0, "天风证券研报"),
    ("ByteDance", 2024, 4, 50.0, "天风证券研报"),
    ("Baidu", 2024, 1, 3.2, "财报"),
    ("Baidu", 2024, 2, 3.5, "财报"),
    ("Baidu", 2024, 3, 4.0, "财报"),
    ("Baidu", 2024, 4, 5.5, "财报"),
    # ---------- 2025 ----------
    ("Alibaba", 2025, 1, 24.6, "FY25Q4财报"),
    ("Alibaba", 2025, 2, 38.6, "FY26Q1财报"),
    ("Alibaba", 2025, 3, 51.0, "FY26Q2财报"),
    ("Alibaba", 2025, 4, 60.0, "FY26Q3财报"),
    ("Tencent", 2025, 1, 27.5, "财报"),
    ("Tencent", 2025, 2, 19.1, "财报"),
    ("Tencent", 2025, 3, 28.0, "财报"),
    ("Tencent", 2025, 4, 38.0, "财报"),
    ("ByteDance", 2025, 1, 55.0, "华泰证券研报"),
    ("ByteDance", 2025, 2, 70.0, "华泰证券研报"),
    ("ByteDance", 2025, 3, 85.0, "华泰证券研报"),
    ("ByteDance", 2025, 4, 110.0, "华泰证券研报"),
    ("Baidu", 2025, 1, 6.5, "财报"),
    ("Baidu", 2025, 2, 7.0, "财报"),
    ("Baidu", 2025, 3, 7.8, "财报"),
    ("Baidu", 2025, 4, 9.5, "财报"),
    # ---------- 2026 Q1 ----------
    ("Alibaba", 2026, 1, 72.0, "FY26Q4财报指引"),
    ("Tencent", 2026, 1, 42.0, "财报"),
    ("ByteDance", 2026, 1, 130.0, "行业研报"),
    ("Baidu", 2026, 1, 11.0, "财报"),
]


# ======================================================================
# TSMC 月度营收 (亿新台币)
# 来源: TSMC 投资者关系页 - 每月10日左右公布
# ======================================================================
TSMC_MONTHLY = [
    # year, month, revenue_twd_bn, yoy_pct, mom_pct
    (2024, 1, 215.8, 7.9, -15.4),
    (2024, 2, 181.7, 11.3, -15.8),
    (2024, 3, 195.2, 34.3, 7.5),
    (2024, 4, 236.0, 59.6, 20.9),
    (2024, 5, 229.6, 30.0, -2.7),
    (2024, 6, 207.9, 32.9, -9.5),
    (2024, 7, 256.9, 44.7, 23.6),
    (2024, 8, 250.9, 32.8, -2.4),
    (2024, 9, 251.9, 39.6, 0.4),
    (2024, 10, 314.2, 29.2, 24.8),
    (2024, 11, 276.0, 34.0, -12.2),
    (2024, 12, 278.2, 57.8, 0.8),
    (2025, 1, 293.2, 35.8, 5.4),
    (2025, 2, 260.0, 43.1, -11.3),
    (2025, 3, 285.9, 46.5, 10.0),
    (2025, 4, 349.6, 48.1, 22.2),
    (2025, 5, 320.5, 39.6, -8.3),
    (2025, 6, 263.7, 26.9, -17.7),
    (2025, 7, 323.2, 25.8, 22.5),
    (2025, 8, 335.8, 33.8, 3.9),
    (2025, 9, 330.0, 31.0, -1.7),
    (2025, 10, 367.5, 17.0, 11.4),
    (2025, 11, 350.2, 26.9, -4.7),
    (2025, 12, 313.5, 12.7, -10.5),
    (2026, 1, 342.3, 16.8, 9.2),
    (2026, 2, 320.5, 23.3, -6.4),
    (2026, 3, 357.4, 25.0, 11.5),
    (2026, 4, 388.5, 11.1, 8.7),
]


# ======================================================================
# 韩国半导体出口 (亿美元) - 韩国MOTIE每月1日公布
# 来源: Korea Ministry of Trade, Industry and Energy
# ======================================================================
KOREA_EXPORTS = [
    # year, month, total_billion_usd, memory_billion_usd, yoy_pct
    (2024, 1, 9.4, 6.4, 56.2),
    (2024, 2, 9.6, 6.4, 65.3),
    (2024, 3, 11.7, 8.4, 35.8),
    (2024, 4, 11.0, 7.8, 56.1),
    (2024, 5, 11.4, 7.8, 54.5),
    (2024, 6, 13.4, 9.8, 50.9),
    (2024, 7, 11.7, 8.8, 50.4),
    (2024, 8, 11.9, 8.7, 38.8),
    (2024, 9, 13.6, 10.1, 36.3),
    (2024, 10, 12.5, 9.1, 40.3),
    (2024, 11, 12.5, 9.3, 30.8),
    (2024, 12, 14.5, 11.0, 31.5),
    (2025, 1, 10.1, 7.3, 7.4),
    (2025, 2, 9.6, 6.6, 0.0),
    (2025, 3, 13.1, 9.7, 11.9),
    (2025, 4, 11.5, 8.4, 4.6),
    (2025, 5, 13.8, 10.0, 21.2),
    (2025, 6, 14.9, 11.0, 11.2),
    (2025, 7, 14.0, 10.6, 19.7),
    (2025, 8, 15.1, 11.5, 27.0),
    (2025, 9, 16.5, 12.7, 21.3),
    (2025, 10, 16.9, 13.2, 35.2),
    (2025, 11, 16.0, 12.5, 28.0),
    (2025, 12, 19.7, 15.6, 35.9),
    (2026, 1, 15.4, 12.3, 52.5),
    (2026, 2, 14.8, 11.8, 54.2),
    (2026, 3, 18.5, 14.9, 41.2),
    (2026, 4, 18.0, 14.5, 56.5),
]


# ======================================================================
# AI 数据中心 vs BTC挖矿 电力消耗 (TWh/年)
# 来源: IEA, Cambridge BTC Electricity Index, Goldman Sachs
# ======================================================================
POWER_DATA = [
    # year, category, twh_per_year
    (2022, "ai_datacenter", 50),
    (2022, "btc_mining", 110),
    (2022, "crypto_other", 30),
    (2023, "ai_datacenter", 85),
    (2023, "btc_mining", 135),
    (2023, "crypto_other", 35),
    (2024, "ai_datacenter", 165),
    (2024, "btc_mining", 175),
    (2024, "crypto_other", 40),
    (2025, "ai_datacenter", 320),
    (2025, "btc_mining", 195),
    (2025, "crypto_other", 45),
    (2026, "ai_datacenter", 550),  # 预估
    (2026, "btc_mining", 210),
    (2026, "crypto_other", 50),
    (2027, "ai_datacenter", 850),  # IEA预估
    (2027, "btc_mining", 220),
    (2027, "crypto_other", 55),
]


def backfill_china_capex():
    conn = get_conn()
    cur = conn.cursor()
    rate_map = {2022: 6.8, 2023: 7.1, 2024: 7.2, 2025: 7.1, 2026: 7.1}
    n = 0
    for company, y, q, cny_bn, src in CHINA_CAPEX:
        usd_bn = round(cny_bn / rate_map.get(y, 7.1), 2)
        cur.execute("""
            INSERT OR REPLACE INTO china_capex_quarterly
            (company, calendar_year, calendar_quarter, capex_billion_cny,
             capex_billion_usd, source, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (company, y, q, cny_bn, usd_bn, src, ""))
        n += 1
    conn.commit()
    conn.close()
    print(f"✅ China cloud capex: {n} rows")


def backfill_tsmc():
    conn = get_conn()
    cur = conn.cursor()
    twd_rate = 32.0  # 30亿台币 ≈ 1亿美元
    n = 0
    for y, m, twd_bn, yoy, mom in TSMC_MONTHLY:
        usd_bn = round(twd_bn / twd_rate, 2)
        cur.execute("""
            INSERT OR REPLACE INTO tsmc_monthly
            (year, month, revenue_billion_twd, revenue_billion_usd,
             yoy_pct, mom_pct, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (y, m, twd_bn, usd_bn, yoy, mom, "TSMC IR"))
        n += 1
    conn.commit()
    conn.close()
    print(f"✅ TSMC monthly: {n} rows")


def backfill_korea():
    conn = get_conn()
    cur = conn.cursor()
    n = 0
    for y, m, total, memory, yoy in KOREA_EXPORTS:
        cur.execute("""
            INSERT OR REPLACE INTO korea_semi_exports
            (year, month, exports_billion_usd, memory_billion_usd, yoy_pct, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (y, m, total, memory, yoy, "Korea MOTIE"))
        n += 1
    conn.commit()
    conn.close()
    print(f"✅ Korea semi exports: {n} rows")


def backfill_power():
    conn = get_conn()
    cur = conn.cursor()
    n = 0
    for y, cat, twh in POWER_DATA:
        cur.execute("""
            INSERT OR REPLACE INTO power_competition
            (year, category, twh_per_year, source)
            VALUES (?, ?, ?, ?)
        """, (y, cat, twh, "IEA + Cambridge BTC Index"))
        n += 1
    conn.commit()
    conn.close()
    print(f"✅ Power competition: {n} rows")


def main():
    extend_schema()
    backfill_china_capex()
    backfill_tsmc()
    backfill_korea()
    backfill_power()


if __name__ == "__main__":
    main()
