import pytest


def test_walk_forward_rolling():
    """walk_forward produces correct rolling splits."""
    from ml_research.splitter import walk_forward

    dates = [f"2020-01-{d:02d}" for d in range(1, 32)]  # 31 dates
    splits = walk_forward(dates, train_days=10, test_days=5, step_days=5, mode="rolling")

    assert len(splits) > 0
    for s in splits:
        assert len(s["train_dates"]) == 10
        assert len(s["test_dates"]) == 5
        # No overlap
        assert set(s["train_dates"]).isdisjoint(set(s["test_dates"]))
        # Train before test
        assert max(s["train_dates"]) < min(s["test_dates"])


def test_walk_forward_expanding():
    """walk_forward expanding window grows train set."""
    from ml_research.splitter import walk_forward

    dates = [f"2020-01-{d:02d}" for d in range(1, 32)]
    splits = walk_forward(dates, train_days=10, test_days=5, step_days=5, mode="expanding")

    assert len(splits) >= 2
    # Expanding: each split's train is longer than previous
    for i in range(1, len(splits)):
        assert len(splits[i]["train_dates"]) >= len(splits[i - 1]["train_dates"])
