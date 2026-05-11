#!/usr/bin/env python3
# backfill_capex.py - 回填四大云厂商历史Capex数据
"""
数据来源：各公司10-Q/10-K财报披露
口径：自然年(Calendar Year)季度（Microsoft财年错位已调整）
单位：亿美元（billion USD）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

# ======================================================================
# 历史Capex数据 (单位: 亿美元 USD billion)
# 来源: 各公司10-Q填报 + 公开财报新闻交叉验证
# 注：Microsoft财年7月起算，需统一到自然年季度
# ======================================================================
CAPEX_HISTORY = [
    # company, calendar_year, calendar_quarter, capex_billion, source
    # ---------- 2022 ----------
    ("AMZN", 2022, 1, 14.3, "10-Q"),
    ("AMZN", 2022, 2, 15.3, "10-Q"),
    ("AMZN", 2022, 3, 16.1, "10-Q"),
    ("AMZN", 2022, 4, 14.7, "10-K"),
    ("MSFT", 2022, 1, 6.6, "10-Q"),
    ("MSFT", 2022, 2, 6.3, "10-K"),
    ("MSFT", 2022, 3, 6.6, "10-Q"),
    ("MSFT", 2022, 4, 7.4, "10-Q"),
    ("GOOGL", 2022, 1, 9.8, "10-Q"),
    ("GOOGL", 2022, 2, 6.8, "10-Q"),
    ("GOOGL", 2022, 3, 7.3, "10-Q"),
    ("GOOGL", 2022, 4, 7.6, "10-K"),
    ("META", 2022, 1, 5.5, "10-Q"),
    ("META", 2022, 2, 7.7, "10-Q"),
    ("META", 2022, 3, 9.5, "10-Q"),
    ("META", 2022, 4, 9.2, "10-K"),
    # ---------- 2023 ----------
    ("AMZN", 2023, 1, 14.0, "10-Q"),
    ("AMZN", 2023, 2, 11.5, "10-Q"),
    ("AMZN", 2023, 3, 12.5, "10-Q"),
    ("AMZN", 2023, 4, 14.6, "10-K"),
    ("MSFT", 2023, 1, 7.8, "10-Q"),
    ("MSFT", 2023, 2, 8.9, "10-K"),
    ("MSFT", 2023, 3, 11.2, "10-Q"),
    ("MSFT", 2023, 4, 11.5, "10-Q"),
    ("GOOGL", 2023, 1, 6.3, "10-Q"),
    ("GOOGL", 2023, 2, 6.9, "10-Q"),
    ("GOOGL", 2023, 3, 8.1, "10-Q"),
    ("GOOGL", 2023, 4, 11.0, "10-K"),
    ("META", 2023, 1, 7.1, "10-Q"),
    ("META", 2023, 2, 6.4, "10-Q"),
    ("META", 2023, 3, 6.8, "10-Q"),
    ("META", 2023, 4, 7.9, "10-K"),
    # ---------- 2024 ----------
    ("AMZN", 2024, 1, 14.9, "10-Q"),
    ("AMZN", 2024, 2, 17.6, "10-Q"),
    ("AMZN", 2024, 3, 22.6, "10-Q"),
    ("AMZN", 2024, 4, 27.8, "10-K"),
    ("MSFT", 2024, 1, 14.0, "10-Q"),
    ("MSFT", 2024, 2, 13.9, "10-K"),
    ("MSFT", 2024, 3, 20.0, "10-Q"),
    ("MSFT", 2024, 4, 22.6, "10-Q"),
    ("GOOGL", 2024, 1, 12.0, "10-Q"),
    ("GOOGL", 2024, 2, 13.2, "10-Q"),
    ("GOOGL", 2024, 3, 13.1, "10-Q"),
    ("GOOGL", 2024, 4, 14.3, "10-K"),
    ("META", 2024, 1, 6.7, "10-Q"),
    ("META", 2024, 2, 8.5, "10-Q"),
    ("META", 2024, 3, 9.2, "10-Q"),
    ("META", 2024, 4, 14.8, "10-K"),
    # ---------- 2025 ----------
    ("AMZN", 2025, 1, 24.3, "10-Q"),
    ("AMZN", 2025, 2, 31.4, "10-Q"),
    ("AMZN", 2025, 3, 34.2, "10-Q"),
    ("AMZN", 2025, 4, 38.4, "10-K"),
    ("MSFT", 2025, 1, 16.7, "10-Q"),
    ("MSFT", 2025, 2, 24.2, "10-K"),
    ("MSFT", 2025, 3, 19.6, "10-Q"),
    ("MSFT", 2025, 4, 19.4, "10-Q"),
    ("GOOGL", 2025, 1, 17.2, "10-Q"),
    ("GOOGL", 2025, 2, 22.4, "10-Q"),
    ("GOOGL", 2025, 3, 24.0, "10-Q"),
    ("GOOGL", 2025, 4, 21.4, "10-K"),
    ("META", 2025, 1, 13.7, "10-Q"),
    ("META", 2025, 2, 17.0, "10-Q"),
    ("META", 2025, 3, 19.4, "10-Q"),
    ("META", 2025, 4, 18.9, "10-K"),
    # ---------- 2026 Q1 ----------
    ("AMZN", 2026, 1, 44.0, "10-Q"),
    ("MSFT", 2026, 1, 31.0, "10-Q"),
    ("GOOGL", 2026, 1, 35.7, "10-Q"),
    ("META", 2026, 1, 19.8, "10-Q"),
]

# ======================================================================
# 全年Capex指引历史
# (公司, 指引年份, 区间下限, 区间上限, 公布日期, 来源)
# ======================================================================
GUIDANCE_HISTORY = [
    # 2024 guidance
    ("AMZN", 2024, 75.0, 75.0, "2024-02-01", "Q4 2023 earnings call"),
    ("MSFT", 2024, 55.0, 55.0, "2024-01-30", "Q2 FY24 earnings"),
    ("GOOGL", 2024, 50.0, 50.0, "2024-02-01", "Q4 2023 earnings"),
    ("META", 2024, 30.0, 37.0, "2024-02-01", "Q4 2023 earnings"),
    ("META", 2024, 35.0, 40.0, "2024-04-24", "Q1 2024 guidance raise"),
    # 2025 guidance
    ("AMZN", 2025, 100.0, 100.0, "2025-02-06", "Q4 2024 earnings"),
    ("AMZN", 2025, 125.0, 125.0, "2025-10-30", "Q3 2025 raise"),
    ("AMZN", 2025, 128.3, 128.3, "2026-02-06", "Q4 2025 actual"),
    ("MSFT", 2025, 80.0, 80.0, "2025-01-29", "Q2 FY25 earnings"),
    ("GOOGL", 2025, 75.0, 75.0, "2025-02-04", "Q4 2024 earnings"),
    ("GOOGL", 2025, 85.0, 85.0, "2025-07-23", "Q2 2025 raise"),
    ("META", 2025, 60.0, 65.0, "2025-01-29", "Q4 2024 earnings"),
    ("META", 2025, 66.0, 72.0, "2025-04-30", "Q1 2025 raise"),
    ("META", 2025, 69.0, 69.0, "2026-01-29", "Q4 2025 actual"),
    # 2026 guidance（最新）
    ("AMZN", 2026, 200.0, 200.0, "2026-02-06", "Q4 2025 guidance"),
    ("MSFT", 2026, 152.0, 152.0, "2026-01-29", "Initial 2026 guidance"),
    ("MSFT", 2026, 190.0, 190.0, "2026-04-29", "Q3 FY26 raise (memory costs)"),
    ("GOOGL", 2026, 175.0, 185.0, "2026-02-04", "Q4 2025 guidance"),
    ("GOOGL", 2026, 180.0, 190.0, "2026-04-29", "Q1 2026 raise"),
    ("META", 2026, 115.0, 135.0, "2026-01-29", "Q4 2025 guidance"),
    ("META", 2026, 125.0, 145.0, "2026-04-29", "Q1 2026 raise"),
]


def backfill():
    conn = get_conn()
    cur = conn.cursor()
    inserted = 0
    for row in CAPEX_HISTORY:
        company, cy, cq, capex, src = row
        # MSFT 财年→自然年的简化映射（MSFT Q1=Cal Q3, Q2=Q4, Q3=Q1, Q4=Q2）
        if company == "MSFT":
            # FY mapping: Cal Q1 = MSFT Q3 of FY
            fy_map = {1: (cy, 3), 2: (cy, 4), 3: (cy + 1, 1), 4: (cy + 1, 2)}
            fy, fq = fy_map[cq]
        else:
            fy, fq = cy, cq
        cur.execute("""
            INSERT OR REPLACE INTO capex_quarterly
            (company, fiscal_year, fiscal_quarter, calendar_year, calendar_quarter,
             capex_billion_usd, source, reported_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (company, fy, fq, cy, cq, capex, src, f"{cy}-Q{cq}", ""))
        inserted += 1

    # 计算YoY
    cur.execute("""
        UPDATE capex_quarterly
        SET yoy_growth = (
            SELECT ROUND((c1.capex_billion_usd - c2.capex_billion_usd) / c2.capex_billion_usd * 100, 1)
            FROM capex_quarterly c1, capex_quarterly c2
            WHERE c1.rowid = capex_quarterly.rowid
              AND c2.company = c1.company
              AND c2.calendar_year = c1.calendar_year - 1
              AND c2.calendar_quarter = c1.calendar_quarter
        )
    """)

    # 指引
    g_inserted = 0
    for row in GUIDANCE_HISTORY:
        company, year, low, high, date, src = row
        cur.execute("""
            INSERT INTO capex_guidance
            (company, guidance_year, guidance_low_billion, guidance_high_billion,
             guidance_point_billion, announced_date, source, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (company, year, low, high, (low + high) / 2, date, src, ""))
        g_inserted += 1

    conn.commit()
    conn.close()
    print(f"✅ Inserted {inserted} capex quarterly rows, {g_inserted} guidance rows")


if __name__ == "__main__":
    backfill()
