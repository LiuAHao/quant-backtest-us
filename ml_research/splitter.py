"""
Walk-Forward 滚动训练/测试切分
"""
from typing import List, Dict


def walk_forward(
    trade_dates: List[str],
    train_days: int = 504,
    test_days: int = 63,
    step_days: int = 63,
    mode: str = "rolling",
) -> List[Dict[str, List[str]]]:
    """
    生成 walk-forward 训练/测试切分。

    Args:
        trade_dates: 排序后的交易日期列表
        train_days: 训练窗口长度（rolling 模式）
        test_days: 测试窗口长度
        step_days: 每次推进的步长
        mode: "rolling"（固定窗口滑动）或 "expanding"（窗口递增）

    Returns:
        List of {"train_dates": [...], "test_dates": [...]}
    """
    n = len(trade_dates)
    splits = []

    # 第一个测试集的起始位置
    start_test = train_days if mode == "rolling" else train_days

    i = start_test
    while i + test_days <= n:
        if mode == "rolling":
            train_start = i - train_days
        else:
            train_start = 0

        train = trade_dates[train_start:i]
        test = trade_dates[i:i + test_days]

        splits.append({
            "train_dates": train,
            "test_dates": test,
        })

        i += step_days

    return splits
