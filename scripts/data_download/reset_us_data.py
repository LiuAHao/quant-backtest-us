from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings


def reset_path(path: Path, *, recreate: bool = True) -> str:
    if path.is_dir():
        shutil.rmtree(path)
        if recreate:
            path.mkdir(parents=True, exist_ok=True)
        return f"reset directory {path}"
    if path.exists():
        path.unlink()
        return f"removed file {path}"
    return f"skipped missing {path}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete old US daily-bar data and download metadata.")
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep the raw single-symbol cache directory instead of clearing it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = [
        settings.US_DAILY_BAR_DIR,
        settings.META_DIR / "download_us_daily_checkpoint.json",
        settings.META_DIR / "download_us_daily_report.json",
        settings.META_DIR / "success_symbols.txt",
        settings.META_DIR / "missing_symbols.txt",
        settings.META_DIR / "failed_symbols.txt",
        settings.META_DIR / "unsupported_symbols.txt",
        settings.META_DIR / "corrupt_year_backups",
    ]
    recreate_overrides: dict[Path, bool] = {
        settings.META_DIR / "corrupt_year_backups": True,
    }
    targets.extend(sorted(settings.META_DIR.glob("download_us_daily_*_checkpoint.json")))
    stage_dirs = sorted(settings.META_DIR.glob("stage_*"))
    targets.extend(stage_dirs)
    for stage_dir in stage_dirs:
        recreate_overrides[stage_dir] = False
    if not args.keep_raw:
        targets.insert(0, settings.US_DAILY_BAR_RAW_DIR)

    for target in targets:
        print(reset_path(target, recreate=recreate_overrides.get(target, target.is_dir())))

    settings.US_DAILY_BAR_DIR.mkdir(parents=True, exist_ok=True)
    settings.US_DAILY_BAR_RAW_DIR.mkdir(parents=True, exist_ok=True)
    settings.META_DIR.mkdir(parents=True, exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
