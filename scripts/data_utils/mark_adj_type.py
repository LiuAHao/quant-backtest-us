"""
daily_bar 元数据标记脚本

标记 daily_bar 中存储的价格类型（前复权/后复权/未复权），
写入 meta.duckdb 的 daily_bar_meta 表中，供 DataLoader 读取。

用法:
    python scripts/mark_adj_type.py --adj_type raw
    python scripts/mark_adj_type.py --adj_type qfq
"""

import argparse
import sys
from pathlib import Path

import duckdb
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings


def mark_adj_type(adj_type: str = "raw"):
    """
    在 meta.duckdb 中标记 daily_bar 的复权类型

    Args:
        adj_type: 复权类型
            - "raw": 未复权（原始价格）
            - "qfq": 前复权
            - "hfq": 后复权
    """
    valid_types = {"raw", "qfq", "hfq"}
    if adj_type not in valid_types:
        raise ValueError(f"adj_type 必须是 {valid_types} 之一，当前: {adj_type}")

    conn = duckdb.connect(str(settings.META_DB_PATH))

    # 创建元数据表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_bar_meta (
            key VARCHAR PRIMARY KEY,
            value VARCHAR,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 插入/更新 adj_type
    conn.execute(f"""
        INSERT INTO daily_bar_meta (key, value, updated_at)
        VALUES ('adj_type', '{adj_type}', '{now}')
        ON CONFLICT (key) DO UPDATE SET
            value = '{adj_type}',
            updated_at = '{now}'
    """)

    # 同时记录说明
    type_desc = {
        "raw": "未复权 - daily_bar 存储原始价格，复权通过 adj_factor 动态计算",
        "qfq": "前复权 - daily_bar 存储以前复权价格",
        "hfq": "后复权 - daily_bar 存储以后复权价格",
    }
    conn.execute(f"""
        INSERT INTO daily_bar_meta (key, value, updated_at)
        VALUES ('adj_type_desc', '{type_desc[adj_type]}', '{now}')
        ON CONFLICT (key) DO UPDATE SET
            value = '{type_desc[adj_type]}',
            updated_at = '{now}'
    """)

    conn.close()
    logger.info(f"daily_bar 复权类型标记为: {adj_type} ({type_desc[adj_type]})")


def get_adj_type() -> str:
    """读取 daily_bar 的复权类型标记"""
    conn = duckdb.connect(str(settings.META_DB_PATH))
    try:
        result = conn.execute(
            "SELECT value FROM daily_bar_meta WHERE key = 'adj_type'"
        ).fetchone()
        return result[0] if result else "unknown"
    except Exception:
        return "unknown"
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="标记 daily_bar 复权类型")
    parser.add_argument("--adj_type", type=str, default="raw",
                        choices=["raw", "qfq", "hfq"],
                        help="复权类型: raw=未复权, qfq=前复权, hfq=后复权")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO")

    mark_adj_type(args.adj_type)

    # 验证
    current = get_adj_type()
    print(f"当前 daily_bar 复权类型: {current}")


if __name__ == "__main__":
    main()
