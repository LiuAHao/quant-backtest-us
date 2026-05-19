from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.engine import BacktestResult


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float, np.integer, np.floating)):
        if pd.isna(value):
            return default
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _series_points(series: pd.Series) -> List[Dict[str, float]]:
    if series is None or len(series) == 0:
        return []

    points: List[Dict[str, float]] = []
    for idx, value in series.items():
        timestamp = pd.to_datetime(idx)
        points.append({
            "date": timestamp.strftime("%Y-%m-%d"),
            "value": _safe_float(value),
        })
    return points


def _series_points_with_key(series: pd.Series, value_key: str, date_key: str = "date") -> List[Dict[str, Any]]:
    if series is None or len(series) == 0:
        return []

    points: List[Dict[str, Any]] = []
    for idx, value in series.items():
        timestamp = pd.to_datetime(idx)
        points.append({
            date_key: timestamp.strftime("%Y-%m-%d"),
            value_key: _safe_float(value),
        })
    return points


def _monthly_returns(equity_curve: pd.Series) -> List[Dict[str, float]]:
    if equity_curve is None or len(equity_curve) == 0:
        return []

    monthly_last = equity_curve.resample("ME").last()
    monthly_return = monthly_last.pct_change()

    results: List[Dict[str, float]] = []
    first_ts = monthly_last.index[0]
    initial_value = equity_curve.iloc[0]
    first_end = _safe_float(monthly_last.loc[first_ts])
    first_ret = (first_end / _safe_float(initial_value)) - 1.0 if _safe_float(initial_value) != 0 else 0.0

    for idx, value in monthly_return.items():
        month_str = pd.to_datetime(idx).strftime("%Y-%m")
        if pd.isna(value) or idx == first_ts:
            results.append({"month": month_str, "return": first_ret})
        else:
            results.append({"month": month_str, "return": _safe_float(value)})
    return results


def _monthly_summary(equity_curve: pd.Series, initial_capital: float) -> List[Dict[str, Any]]:
    if equity_curve is None or len(equity_curve) == 0:
        return []

    equity_curve = equity_curve.sort_index()
    monthly_last = equity_curve.resample("ME").last()
    monthly_first = equity_curve.resample("MS").first()
    monthly_return = monthly_last.pct_change()

    rows: List[Dict[str, Any]] = []
    for idx in monthly_last.index:
        month_key = pd.to_datetime(idx).strftime("%Y-%m")
        start_idx = pd.Timestamp(year=idx.year, month=idx.month, day=1)
        start_value = monthly_first.get(start_idx, monthly_last.loc[idx])
        rows.append({
            "month": month_key,
            "start_value": _safe_float(start_value),
            "end_value": _safe_float(monthly_last.loc[idx]),
            "return": _safe_float(monthly_return.loc[idx]) if idx in monthly_return.index else 0.0,
            "cum_return": _safe_float((monthly_last.loc[idx] / initial_capital) - 1.0),
        })
    return rows


def _trade_rows(trades: pd.DataFrame) -> List[Dict[str, Any]]:
    if trades is None or len(trades) == 0:
        return []

    rows: List[Dict[str, Any]] = []
    for row in trades.to_dict(orient="records"):
        trade_date = pd.to_datetime(row.get("trade_date"))
        trade_date_str = "" if pd.isna(trade_date) else trade_date.strftime("%Y-%m-%d")
        trade_time_str = "" if pd.isna(trade_date) else trade_date.strftime("%Y-%m-%d %H:%M:%S")
        rows.append({
            "trade_date": trade_date_str,
            "trade_time": trade_time_str,
            "ts_code": row.get("ts_code", ""),
            "side": str(row.get("side", "")).upper(),
            "volume": int(_safe_float(row.get("volume"), 0)),
            "price": round(_safe_float(row.get("price"), 0), 4),
            "amount": round(_safe_float(row.get("amount"), 0), 2),
            "commission": round(_safe_float(row.get("commission"), 0), 2),
            "stamp_duty": round(_safe_float(row.get("stamp_duty"), 0), 2),
            "realized_pnl": round(_safe_float(row.get("realized_pnl"), 0), 2),
        })
    return rows


def _daily_rows(equity_curve: pd.Series, initial_capital: float) -> List[Dict[str, Any]]:
    if equity_curve is None or len(equity_curve) == 0:
        return []

    equity_curve = equity_curve.sort_index()
    daily_returns = equity_curve.pct_change().fillna(0.0)
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve / rolling_max) - 1.0

    rows: List[Dict[str, Any]] = []
    for idx, value in equity_curve.items():
        ts = pd.to_datetime(idx)
        rows.append({
            "date": ts.strftime("%Y-%m-%d"),
            "total_value": _safe_float(value),
            "daily_return": _safe_float(daily_returns.loc[idx]),
            "cumulative_return": _safe_float((value / initial_capital) - 1.0),
            "drawdown": _safe_float(drawdown.loc[idx]),
            "high_water_mark": _safe_float(rolling_max.loc[idx]),
        })
    return rows


def _trade_side_breakdown(trades: pd.DataFrame) -> List[Dict[str, Any]]:
    if trades is None or len(trades) == 0 or "side" not in trades.columns:
        return []

    rows: List[Dict[str, Any]] = []
    for side, count in trades["side"].astype(str).str.upper().value_counts().items():
        rows.append({
            "side": side,
            "count": int(count),
        })
    return rows


def _max_drawdown_period(equity_curve: pd.Series) -> Dict[str, Any]:
    if equity_curve is None or len(equity_curve) == 0:
        return {}

    equity_curve = equity_curve.sort_index()
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve / rolling_max) - 1.0

    trough_idx = drawdown.idxmin()
    peak_window = equity_curve.loc[:trough_idx]
    peak_idx = peak_window.idxmax()

    peak_ts = pd.to_datetime(peak_idx)
    trough_ts = pd.to_datetime(trough_idx)
    peak_value = _safe_float(equity_curve.loc[peak_idx])
    trough_value = _safe_float(equity_curve.loc[trough_idx])

    recovery_window = equity_curve.loc[trough_idx:]
    recovery_window = recovery_window[recovery_window >= peak_value]
    recovery_idx = recovery_window.index[0] if len(recovery_window) else None

    result: Dict[str, Any] = {
        "start": {
            "date": peak_ts.strftime("%Y-%m-%d"),
            "value": peak_value,
        },
        "end": {
            "date": trough_ts.strftime("%Y-%m-%d"),
            "value": trough_value,
        },
        "drawdown": _safe_float(drawdown.loc[trough_idx]),
        "duration_days": int((trough_ts - peak_ts).days),
    }
    if recovery_idx is not None:
        recovery_ts = pd.to_datetime(recovery_idx)
        result["recovery"] = {
            "date": recovery_ts.strftime("%Y-%m-%d"),
            "value": _safe_float(equity_curve.loc[recovery_idx]),
        }
        result["recovery_days"] = int((recovery_ts - peak_ts).days)
    else:
        result["recovery"] = None
        result["recovery_days"] = None
    return result


def _metric_cards(result: BacktestResult, daily_returns: pd.Series) -> List[Dict[str, Any]]:
    best_day = daily_returns.max() if len(daily_returns) else 0.0
    worst_day = daily_returns.min() if len(daily_returns) else 0.0

    return [
        {"label": "总收益率", "value": result.total_return, "format": "pct", "tone": "positive" if result.total_return >= 0 else "negative"},
        {"label": "年化收益", "value": result.annual_return, "format": "pct", "tone": "positive" if result.annual_return >= 0 else "negative"},
        {"label": "最大回撤", "value": result.max_drawdown, "format": "pct", "tone": "negative"},
        {"label": "夏普比率", "value": result.sharpe_ratio, "format": "number", "tone": "neutral"},
        {"label": "索提诺比率", "value": result.sortino_ratio, "format": "number", "tone": "neutral"},
        {"label": "卡尔马比率", "value": result.calmar_ratio, "format": "number", "tone": "neutral"},
        {"label": "年化波动", "value": result.volatility, "format": "pct", "tone": "neutral"},
        {"label": "下行波动", "value": result.downside_volatility, "format": "pct", "tone": "neutral"},
        {"label": "最佳单日", "value": best_day, "format": "pct", "tone": "positive" if best_day >= 0 else "negative"},
        {"label": "最差单日", "value": worst_day, "format": "pct", "tone": "negative" if worst_day < 0 else "positive"},
        {"label": "交易次数", "value": result.trade_count, "format": "integer", "tone": "neutral"},
        {"label": "盈亏比", "value": result.profit_loss_ratio, "format": "number", "tone": "neutral"},
        {"label": "平均持仓天数", "value": result.avg_holding_days, "format": "number", "tone": "neutral"},
        {"label": "换手率", "value": result.turnover, "format": "number", "tone": "neutral"},
    ]


def build_report_payload(
    result: BacktestResult,
    strategy_name: str,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    equity_curve = result.equity_curve.sort_index()
    daily_returns = result.daily_returns.sort_index() if len(result.daily_returns) else result.daily_returns

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve / rolling_max) - 1.0 if len(equity_curve) else pd.Series(dtype=float)
    latest_equity = equity_curve.iloc[-1] if len(equity_curve) else result.final_value
    cumulative_return = (equity_curve / result.initial_capital) - 1.0 if len(equity_curve) else pd.Series(dtype=float)
    rolling_20_return = equity_curve.pct_change(20) if len(equity_curve) else pd.Series(dtype=float)
    rolling_20_vol = daily_returns.rolling(20).std() * np.sqrt(252) if len(daily_returns) else pd.Series(dtype=float)
    rolling_60_vol = daily_returns.rolling(60).std() * np.sqrt(252) if len(daily_returns) else pd.Series(dtype=float)
    trade_pnl = result.trades["realized_pnl"] if result.trades is not None and len(result.trades) > 0 and "realized_pnl" in result.trades.columns else pd.Series(dtype=float)
    max_drawdown_period = _max_drawdown_period(equity_curve)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "header": {
            "title": title or f"{strategy_name} 回测看板",
            "subtitle": subtitle or "量化回测结果与风险表现总览",
            "strategy_name": strategy_name,
            "date_range": {
                "start": result.start_date.strftime("%Y-%m-%d"),
                "end": result.end_date.strftime("%Y-%m-%d"),
            },
        },
        "hero": {
            "initial_capital": _safe_float(result.initial_capital),
            "final_value": _safe_float(latest_equity),
            "pnl": _safe_float(latest_equity - result.initial_capital),
            "return_pct": _safe_float((latest_equity / result.initial_capital) - 1.0),
            "trade_count": int(result.trade_count),
            "win_rate": _safe_float(result.win_rate),
            "max_drawdown": _safe_float(result.max_drawdown),
            "sharpe_ratio": _safe_float(result.sharpe_ratio),
        },
        "metrics": _metric_cards(result, daily_returns),
        "summary": {
            "days": int(len(equity_curve)),
            "start_value": _safe_float(equity_curve.iloc[0]) if len(equity_curve) else _safe_float(result.initial_capital),
            "end_value": _safe_float(latest_equity),
            "min_value": _safe_float(equity_curve.min()) if len(equity_curve) else _safe_float(result.initial_capital),
            "max_value": _safe_float(equity_curve.max()) if len(equity_curve) else _safe_float(result.initial_capital),
            "avg_daily_return": _safe_float(daily_returns.mean()) if len(daily_returns) else 0.0,
            "volatility": _safe_float(daily_returns.std() * np.sqrt(252)) if len(daily_returns) else 0.0,
            "best_day": _safe_float(daily_returns.max()) if len(daily_returns) else 0.0,
            "worst_day": _safe_float(daily_returns.min()) if len(daily_returns) else 0.0,
            "max_drawdown_period": max_drawdown_period,
            "benchmark": {
                "available": result.benchmark_available,
                "benchmark_return": _safe_float(result.benchmark_return) if result.benchmark_available else None,
                "excess_return": _safe_float(result.excess_return) if result.benchmark_available else None,
                "alpha": _safe_float(result.alpha) if result.benchmark_available else None,
                "beta": _safe_float(result.beta) if result.benchmark_available else None,
                "tracking_error": _safe_float(result.tracking_error) if result.benchmark_available else None,
                "information_ratio": _safe_float(result.information_ratio) if result.benchmark_available else None,
            },
        },
        "charts": {
            "equity_curve": _series_points(equity_curve),
            "cumulative_return": _series_points(cumulative_return),
            "daily_returns": _series_points(daily_returns),
            "drawdown": _series_points(drawdown),
            "rolling_20d_return": _series_points(rolling_20_return),
            "rolling_20d_volatility": _series_points(rolling_20_vol),
            "rolling_60d_volatility": _series_points(rolling_60_vol),
            "monthly_returns": _monthly_returns(equity_curve),
            "trade_pnl": _series_points_with_key(trade_pnl, "pnl", "trade_date"),
            "trade_side_breakdown": _trade_side_breakdown(result.trades),
            "benchmark_curve": _series_points(result.benchmark_curve) if result.benchmark_available and result.benchmark_curve is not None else [],
            "benchmark_daily_returns": _series_points(result.benchmark_daily_returns) if result.benchmark_available and result.benchmark_daily_returns is not None else [],
        },
        "tables": {
            "trades": _trade_rows(result.trades),
            "daily_performance": _daily_rows(equity_curve, result.initial_capital),
            "monthly_performance": _monthly_summary(equity_curve, result.initial_capital),
        },
    }


def write_payload_json(payload: Dict[str, Any], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def write_html_report(payload: Dict[str, Any], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload_json = json.dumps(payload, ensure_ascii=False)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>回测报告</title>
  <style>
    :root {{
      --panel: rgba(255, 255, 255, 0.92);
      --ink: #162033;
      --muted: #61708a;
      --up: #cb4b37;
      --down: #15803d;
      --accent: #2257d6;
      --line: #d9e2ef;
      --grid: #e8eef8;
      --shadow: 0 16px 40px rgba(31, 50, 81, 0.08);
      --radius: 20px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(120, 167, 255, 0.20), transparent 34%),
        radial-gradient(circle at top right, rgba(33, 120, 103, 0.10), transparent 26%),
        linear-gradient(180deg, #f7faff 0%, #eff3f9 55%, #ebf0f6 100%);
    }}
    .container {{ max-width: 1360px; margin: 34px auto 40px; padding: 0 22px; }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 20px;
      margin-bottom: 18px;
      padding: 24px 28px;
      background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(244,248,255,0.9));
      border: 1px solid rgba(217, 226, 239, 0.85);
      border-radius: 26px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
    }}
    h1 {{ margin: 0; font-size: 34px; letter-spacing: .01em; }}
    .sub {{ color: var(--muted); margin-top: 7px; font-size: 14px; }}
    .period-chip {{
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.84);
      color: var(--muted);
      white-space: nowrap;
      font-size: 13px;
    }}
    .grid {{ display: grid; gap: 16px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid rgba(217, 226, 239, 0.9);
      border-radius: var(--radius);
      padding: 18px 20px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .hero-layout {{ grid-template-columns: minmax(0, 2.15fr) minmax(320px, 0.85fr); align-items: start; }}
    .chart-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; }}
    .eyebrow {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    .chart-title {{ margin: 4px 0 0; font-size: 18px; }}
    .chart-note {{ color: var(--muted); font-size: 12px; max-width: 340px; text-align: right; line-height: 1.6; }}
    .card-label {{ color: var(--muted); font-size: 12px; }}
    .card-value {{ font-size: 26px; font-weight: 700; margin-top: 8px; letter-spacing: -.02em; }}
    .card-foot {{ font-size: 12px; color: var(--muted); margin-top: 8px; min-height: 18px; }}
    .up {{ color: var(--up); }}
    .down {{ color: var(--down); }}
    .summary-list {{ display: grid; gap: 10px; }}
    .summary-item {{
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(247,250,255,.95), rgba(255,255,255,.92));
    }}
    .summary-item strong {{ display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; font-weight: 600; }}
    .summary-value {{ font-size: 18px; font-weight: 700; }}
    .summary-meta {{ margin-top: 6px; color: var(--muted); font-size: 12px; }}
    .chart-shell {{
      padding: 10px 12px 6px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: linear-gradient(180deg, #fbfdff 0%, #f5f8fd 100%);
      position: relative;
    }}
    svg {{ width: 100%; height: 340px; display: block; }}
    .mono {{ font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #ecf0f6; padding: 10px 12px; text-align: left; }}
    th {{ color: #4b5563; background: #f7f9fc; position: sticky; top: 0; }}
    .table-wrap {{ max-height: 420px; overflow: auto; border: 1px solid var(--line); border-radius: 10px; }}
    .footer {{ color: var(--muted); font-size: 12px; margin-top: 10px; }}
    /* Metric summary table */
    .metric-summary {{ margin-top: 16px; }}
    .metric-summary-grid {{ display: flex; gap: 0; flex-wrap: wrap; }}
    .metric-group {{ flex: 1; min-width: 280px; }}
    .metric-group-title {{
      padding: 10px 16px;
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
      background: #f7f9fc;
      border-bottom: 1px solid var(--line);
    }}
    .metric-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 16px;
      border-bottom: 1px solid #ecf0f6;
    }}
    .metric-row-label {{ color: var(--muted); font-size: 13px; }}
    .metric-row-value {{ font-size: 15px; font-weight: 700; }}
    /* Monthly heatmap */
    .heatmap-wrap {{ overflow-x: auto; }}
    .heatmap {{ display: grid; grid-template-columns: 50px repeat(12, 1fr); gap: 3px; }}
    .heatmap-corner {{ background: transparent; }}
    .heatmap-month {{
      text-align: center;
      font-size: 12px;
      color: var(--muted);
      padding: 6px 0;
      font-weight: 600;
    }}
    .heatmap-year {{
      display: flex;
      align-items: center;
      font-size: 13px;
      font-weight: 700;
      color: var(--ink);
    }}
    .heatmap-cell {{
      text-align: center;
      padding: 10px 4px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      min-width: 52px;
    }}
    .heatmap-cell.empty {{ background: #f3f5f9; color: var(--muted); }}
    /* Chart tooltip */
    .chart-tooltip {{
      position: absolute;
      background: rgba(255,255,255,0.97);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 12px;
      box-shadow: 0 8px 24px rgba(31,50,81,0.12);
      pointer-events: none;
      z-index: 10;
      min-width: 160px;
      transform: translateX(-50%);
      top: 10px;
    }}
    .chart-tooltip strong {{ display: block; margin-bottom: 4px; font-size: 13px; }}
    .chart-tooltip div {{ margin-top: 2px; }}
    .hover-line {{ stroke: var(--accent); stroke-width: 1; stroke-dasharray: 4 4; opacity: 0.5; }}
    @media (max-width: 980px) {{
      .header {{ display: block; }}
      .period-chip {{ display: inline-flex; margin-top: 14px; }}
      .hero-layout {{ grid-template-columns: 1fr; }}
      .chart-head {{ display: block; }}
      .chart-note {{ text-align: left; margin-top: 8px; max-width: none; }}
      svg {{ height: 320px; }}
      .metric-group {{ min-width: 100%; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1 id="title"></h1>
        <div class="sub" id="subtitle"></div>
      </div>
      <div class="period-chip mono" id="range"></div>
    </div>
    <div class="panel metric-summary" id="metricSummaryPanel">
      <h3 class="chart-title">回测指标总表</h3>
      <div class="metric-summary-grid" id="metricSummary"></div>
    </div>
    <div class="grid hero-layout" style="margin-top:16px;">
      <div class="panel">
        <div class="chart-head">
          <div>
            <div class="eyebrow">Capital Curve</div>
            <h3 class="chart-title">资金曲线与最大回撤区间</h3>
          </div>
          <div class="chart-note" id="drawdownCaption"></div>
        </div>
        <div class="chart-shell" id="equityChartShell">
          <div class="chart-tooltip" id="equityTooltip" style="display:none;"></div>
          <svg id="equityChart" viewBox="0 0 960 360"></svg>
        </div>
      </div>
      <div class="panel">
        <div class="eyebrow">Drawdown Focus</div>
        <h3 class="chart-title">风险摘要</h3>
        <div class="summary-list" id="drawdownSummary"></div>
      </div>
    </div>
    <div class="panel" style="margin-top:16px;">
      <div class="chart-head">
        <div>
          <div class="eyebrow">Monthly Returns</div>
          <h3 class="chart-title">月度收益热力图</h3>
        </div>
        <div class="chart-note">颜色深浅表示收益幅度，红色为正收益，绿色为负收益。</div>
      </div>
      <div class="heatmap-wrap" id="monthlyHeatmap"></div>
    </div>
    <div class="panel" style="margin-top:16px;">
      <h3 class="chart-title">成交明细</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>日期</th><th>代码</th><th>方向</th><th>数量</th><th>价格</th><th>金额</th><th>手续费</th><th>印花税</th><th>已实现盈亏</th></tr></thead>
          <tbody id="tradeRows"></tbody>
        </table>
      </div>
      <div class="footer" id="footer"></div>
    </div>
  </div>
  <script>
    const payload = {payload_json};
    const fmtPct = v => `${{Number(v) >= 0 ? '+' : ''}}${{(Number(v) * 100).toFixed(2)}}%`;
    const fmtNum = v => Number(v).toLocaleString('zh-CN', {{ maximumFractionDigits: 2 }});
    const fmtDate = v => v || '--';

    document.getElementById('title').textContent = payload.header.title;
    document.getElementById('subtitle').textContent = payload.header.subtitle;
    document.getElementById('range').textContent = `${{payload.header.date_range.start}} 至 ${{payload.header.date_range.end}}`;

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[ch]));
    }}

    function buildTicks(points, count = 6) {{
      if (!points || points.length === 0) return [];
      if (points.length <= count) return points.map((point, index) => ({{ point, index }}));
      const lastIndex = points.length - 1;
      const indices = new Set([0, lastIndex]);
      for (let i = 1; i < count - 1; i += 1) {{
        indices.add(Math.round((lastIndex * i) / (count - 1)));
      }}
      return [...indices].sort((a, b) => a - b).map(index => ({{ point: points[index], index }}));
    }}

    // Build cumulative return and daily return lookup maps
    const dailyReturnMap = new Map((payload.charts.daily_returns || []).map(p => [p.date, p.value]));
    const cumulativeReturnMap = new Map((payload.charts.cumulative_return || []).map(p => [p.date, p.value]));
    const equityPoints = payload.charts.equity_curve || [];
    const firstEquity = equityPoints.length > 0 ? Number(equityPoints[0].value) : 1;

    function drawEquityChart(svgId, points, ddPeriod) {{
      const svg = document.getElementById(svgId);
      const shell = document.getElementById('equityChartShell');
      const tooltip = document.getElementById('equityTooltip');
      const W = 960, H = 360;
      const P = {{ top: 24, right: 20, bottom: 64, left: 74 }};
      if (!points || points.length === 0) {{
        svg.innerHTML = '';
        return;
      }}

      const vals = points.map(p => Number(p.value ?? 0));
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      const range = (max - min) || 1;
      const plotW = W - P.left - P.right;
      const plotH = H - P.top - P.bottom;
      const step = vals.length > 1 ? plotW / (vals.length - 1) : 0;
      const xAt = index => P.left + index * step;
      const yAt = value => P.top + plotH - ((value - min) / range) * plotH;
      const coords = vals.map((v, i) => [xAt(i), yAt(v)]);
      const path = coords.map((p, i) => `${{i ? 'L' : 'M'}}${{p[0].toFixed(2)}},${{p[1].toFixed(2)}}`).join(' ');
      const area = `${{path}} L${{P.left + plotW}},${{P.top + plotH}} L${{P.left}},${{P.top + plotH}} Z`;

      const yTicks = Array.from({{ length: 5 }}, (_, i) => {{
        const value = min + ((4 - i) / 4) * range;
        const y = yAt(value);
        return `<g><line x1="${{P.left}}" y1="${{y}}" x2="${{P.left + plotW}}" y2="${{y}}" stroke="var(--grid)" stroke-dasharray="4 6"/><text x="${{P.left - 10}}" y="${{y + 4}}" text-anchor="end" font-size="11" fill="var(--muted)" class="mono">${{escapeHtml(fmtNum(value))}}</text></g>`;
      }}).join('');

      const xTicks = buildTicks(points, 6).map(({{ point, index }}) => {{
        const x = xAt(index);
        return `<g><line x1="${{x}}" y1="${{P.top + plotH}}" x2="${{x}}" y2="${{P.top + plotH + 6}}" stroke="var(--line)"/><text x="${{x}}" y="${{H - 20}}" text-anchor="middle" font-size="11" fill="var(--muted)">${{escapeHtml(point.date.slice(5))}}</text></g>`;
      }}).join('');

      let ddMarkup = '';
      if (ddPeriod && ddPeriod.start && ddPeriod.end) {{
        const startIndex = points.findIndex(p => p.date === ddPeriod.start.date);
        const endIndex = points.findIndex(p => p.date === ddPeriod.end.date);
        if (startIndex >= 0 && endIndex >= 0) {{
          const sx = xAt(startIndex);
          const ex = xAt(endIndex);
          const sy = yAt(Number(ddPeriod.start.value));
          const ey = yAt(Number(ddPeriod.end.value));
          ddMarkup += `<rect x="${{Math.min(sx, ex)}}" y="${{P.top}}" width="${{Math.max(6, Math.abs(ex - sx))}}" height="${{plotH}}" fill="rgba(203,75,55,0.08)"/>`;
          ddMarkup += `<line x1="${{sx}}" y1="${{P.top}}" x2="${{sx}}" y2="${{P.top + plotH}}" stroke="#d97706" stroke-dasharray="5 6"/>`;
          ddMarkup += `<line x1="${{ex}}" y1="${{P.top}}" x2="${{ex}}" y2="${{P.top + plotH}}" stroke="#cb4b37" stroke-dasharray="5 6"/>`;
          ddMarkup += `<circle cx="${{sx}}" cy="${{sy}}" r="5.5" fill="#d97706" stroke="#fff" stroke-width="2"/>`;
          ddMarkup += `<circle cx="${{ex}}" cy="${{ey}}" r="5.5" fill="#cb4b37" stroke="#fff" stroke-width="2"/>`;
          ddMarkup += `<g><rect x="${{Math.max(P.left, sx - 36)}}" y="${{Math.max(P.top + 8, sy - 42)}}" width="72" height="24" rx="12" fill="#fff7ed" stroke="rgba(217,119,6,.28)"/><text x="${{sx}}" y="${{Math.max(P.top + 24, sy - 26)}}" text-anchor="middle" font-size="11" fill="#9a3412">回撤起点</text></g>`;
          ddMarkup += `<g><rect x="${{Math.min(P.left + plotW - 72, ex - 36)}}" y="${{Math.max(P.top + 8, ey - 42)}}" width="72" height="24" rx="12" fill="#fff1f2" stroke="rgba(203,75,55,.24)"/><text x="${{ex}}" y="${{Math.max(P.top + 24, ey - 26)}}" text-anchor="middle" font-size="11" fill="#9f1239">回撤终点</text></g>`;
        }}
      }}

      svg.innerHTML = `
        <rect x="0" y="0" width="${{W}}" height="${{H}}" rx="18" fill="url(#equityBg)"/>
        <defs>
          <linearGradient id="equityBg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#fbfdff" />
            <stop offset="100%" stop-color="#f4f8fe" />
          </linearGradient>
          <linearGradient id="equityArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="rgba(34,87,214,0.30)" />
            <stop offset="100%" stop-color="rgba(34,87,214,0.03)" />
          </linearGradient>
        </defs>
        ${{yTicks}}
        <line x1="${{P.left}}" y1="${{P.top + plotH}}" x2="${{P.left + plotW}}" y2="${{P.top + plotH}}" stroke="var(--line)" />
        ${{xTicks}}
        ${{ddMarkup}}
        <path d="${{area}}" fill="url(#equityArea)"></path>
        <path d="${{path}}" fill="none" stroke="var(--accent)" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"></path>
        <line id="hoverLine" x1="0" y1="${{P.top}}" x2="0" y2="${{P.top + plotH}}" class="hover-line" style="display:none;" />
      `;

      // Hover interaction
      const svgRect = svg.getBoundingClientRect.bind(svg);
      shell.addEventListener('mousemove', (e) => {{
        const rect = svg.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const svgX = (mouseX / rect.width) * W;
        if (svgX < P.left || svgX > P.left + plotW) {{
          tooltip.style.display = 'none';
          document.getElementById('hoverLine').style.display = 'none';
          return;
        }}
        const ratio = (svgX - P.left) / plotW;
        const idx = Math.round(ratio * (points.length - 1));
        const clampedIdx = Math.max(0, Math.min(points.length - 1, idx));
        const point = points[clampedIdx];
        if (!point) return;

        const hoverLine = document.getElementById('hoverLine');
        const lineX = xAt(clampedIdx);
        hoverLine.setAttribute('x1', lineX);
        hoverLine.setAttribute('x2', lineX);
        hoverLine.style.display = '';

        const dailyRet = dailyReturnMap.get(point.date);
        const cumRet = cumulativeReturnMap.get(point.date) ?? (firstEquity ? Number(point.value) / firstEquity - 1 : 0);
        const dailyRetStr = dailyRet != null ? fmtPct(dailyRet) : '--';
        const cumRetStr = cumRet != null ? fmtPct(cumRet) : '--';
        const dailyCls = dailyRet != null && Number(dailyRet) >= 0 ? 'up' : 'down';
        const cumCls = cumRet != null && Number(cumRet) >= 0 ? 'up' : 'down';

        tooltip.innerHTML = `<strong>${{escapeHtml(point.date)}}</strong>`
          + `<div>当日收益：<b class="${{dailyCls}}">${{dailyRetStr}}</b></div>`
          + `<div>累计收益：<b class="${{cumCls}}">${{cumRetStr}}</b></div>`
          + `<div>净值：${{fmtNum(Number(point.value))}}</div>`;
        tooltip.style.display = 'block';

        const tipWidth = 180;
        let tipLeft = mouseX;
        if (tipLeft - tipWidth / 2 < 0) tipLeft = tipWidth / 2;
        if (tipLeft + tipWidth / 2 > rect.width) tipLeft = rect.width - tipWidth / 2;
        tooltip.style.left = tipLeft + 'px';
      }});

      shell.addEventListener('mouseleave', () => {{
        tooltip.style.display = 'none';
        document.getElementById('hoverLine').style.display = 'none';
      }});
    }}

    // Metric summary table
    function renderMetricSummary() {{
      const el = document.getElementById('metricSummary');
      const metrics = payload.metrics || [];
      const trades = payload.tables?.trades || [];
      const realizedTrades = trades.filter(t => Number(t.realized_pnl || 0) !== 0);
      const profitCount = realizedTrades.filter(t => Number(t.realized_pnl) > 0).length;
      const lossCount = realizedTrades.filter(t => Number(t.realized_pnl) < 0).length;
      const ddDays = payload.summary?.max_drawdown_period?.duration_days;
      const pnl = payload.hero ? payload.hero.pnl : 0;
      const pnlCls = Number(pnl) >= 0 ? 'up' : 'down';

      function findMetric(label) {{
        const m = metrics.find(item => item.label === label);
        if (!m) return '--';
        if (m.format === 'pct') return fmtPct(m.value);
        if (m.format === 'integer') return String(Math.round(Number(m.value)));
        return fmtNum(Number(m.value));
      }}

      const groups = [
        {{
          title: '概览',
          items: [
            ['初始资金', payload.hero ? fmtNum(payload.hero.initial_capital) : '--'],
            ['期末权益', payload.hero ? fmtNum(payload.hero.final_value) : '--'],
            ['净利润', payload.hero ? fmtNum(payload.hero.pnl) : '--'],
            ['总收益率', findMetric('总收益率')],
            ['年化收益率', findMetric('年化收益')],
            ['胜率', payload.hero ? fmtPct(payload.hero.win_rate) : '--'],
          ]
        }},
        {{
          title: '风险',
          items: [
            ['最大回撤', findMetric('最大回撤')],
            ['夏普比率', findMetric('夏普比率')],
            ['年化波动', findMetric('年化波动')],
            ['最佳单日', findMetric('最佳单日')],
            ['最差单日', findMetric('最差单日')],
            ['回撤持续天数', ddDays != null ? String(ddDays) : '--'],
            ['回测交易日', payload.summary?.days ? String(payload.summary.days) : '--'],
          ]
        }},
        {{
          title: '交易',
          items: [
            ['盈亏比', findMetric('盈亏比')],
            ['交易次数', findMetric('交易次数')],
            ['盈利次数', profitCount ? String(profitCount) : '--'],
            ['亏损次数', lossCount ? String(lossCount) : '--'],
          ]
        }},
      ];

      el.innerHTML = groups.map(g => {{
        const rows = g.items.map(([label, value]) => {{
          const cls = String(value).startsWith('-') ? 'down' : (String(value).startsWith('+') ? 'up' : '');
          return `<div class="metric-row"><span class="metric-row-label">${{escapeHtml(label)}}</span><span class="metric-row-value mono ${{cls}}">${{escapeHtml(value)}}</span></div>`;
        }}).join('');
        return `<div class="metric-group"><div class="metric-group-title">${{escapeHtml(g.title)}}</div>${{rows}}</div>`;
      }}).join('');
    }}

    // Monthly heatmap
    function renderMonthlyHeatmap() {{
      const el = document.getElementById('monthlyHeatmap');
      const points = payload.charts.monthly_returns || [];
      if (points.length === 0) {{
        el.innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted);">暂无月度收益数据</div>';
        return;
      }}

      const yearMap = new Map();
      points.forEach(p => {{
        const parts = String(p.month || '').split('-');
        if (parts.length < 2) return;
        const year = parts[0];
        const month = Number(parts[1]);
        if (!yearMap.has(year)) yearMap.set(year, new Map());
        yearMap.get(year).set(month, Number(p.return ?? 0));
      }});

      const years = [...yearMap.keys()].sort();
      const months = Array.from({{length: 12}}, (_, i) => i + 1);

      function heatStyle(value) {{
        if (value == null || isNaN(Number(value))) return 'background:#f3f5f9;';
        const abs = Math.min(Math.abs(Number(value)) / 0.15, 1);
        const alpha = 0.22 + abs * 0.68;
        const color = Number(value) >= 0
          ? `rgba(225, 29, 72, ${{alpha}})`
          : `rgba(22, 163, 74, ${{alpha}})`;
        return `background:${{color}};`;
      }}

      let html = '<div class="heatmap">';
      html += '<div class="heatmap-corner"></div>';
      months.forEach(m => {{ html += `<div class="heatmap-month">${{m}}</div>`; }});
      years.forEach(year => {{
        html += `<div class="heatmap-year">${{year}}</div>`;
        months.forEach(m => {{
          const val = yearMap.get(year)?.get(m);
          if (val !== undefined) {{
            const style = heatStyle(val);
            const cls = Number(val) >= 0 ? 'up' : 'down';
            html += `<div class="heatmap-cell" style="${{style}}"><span class="${{cls}}">${{fmtPct(val)}}</span></div>`;
          }} else {{
            html += '<div class="heatmap-cell empty">-</div>';
          }}
        }});
      }});
      html += '</div>';
      el.innerHTML = html;
    }}

    function renderDrawdownSummary(period) {{
      const el = document.getElementById('drawdownSummary');
      const caption = document.getElementById('drawdownCaption');
      if (!period || !period.start || !period.end) {{
        el.innerHTML = '<div class="summary-item"><strong>最大回撤</strong><div class="summary-value">无有效数据</div></div>';
        caption.textContent = '未识别到可用的回撤区间。';
        return;
      }}
      caption.textContent = `最大回撤 ${{fmtPct(period.drawdown)}}，起于 ${{period.start.date}}，止于 ${{period.end.date}}。`;
      el.innerHTML = `
        <div class="summary-item">
          <strong>最大回撤幅度</strong>
          <div class="summary-value down mono">${{fmtPct(period.drawdown)}}</div>
          <div class="summary-meta">从峰值到谷值共 ${{period.duration_days ?? 0}} 天</div>
        </div>
        <div class="summary-item">
          <strong>回撤起点</strong>
          <div class="summary-value mono">${{fmtDate(period.start.date)}}</div>
          <div class="summary-meta">资金 ${{fmtNum(period.start.value)}}</div>
        </div>
        <div class="summary-item">
          <strong>回撤终点</strong>
          <div class="summary-value mono">${{fmtDate(period.end.date)}}</div>
          <div class="summary-meta">资金 ${{fmtNum(period.end.value)}}</div>
        </div>
        <div class="summary-item">
          <strong>修复状态</strong>
          <div class="summary-value mono">${{period.recovery ? fmtDate(period.recovery.date) : '尚未修复'}}</div>
          <div class="summary-meta">${{period.recovery_days != null ? `从起点算起 ${{period.recovery_days}} 天修复` : '截至回测结束仍未回到前高'}}</div>
        </div>
      `;
    }}

    renderDrawdownSummary(payload.summary.max_drawdown_period);
    drawEquityChart('equityChart', payload.charts.equity_curve, payload.summary.max_drawdown_period);
    renderMetricSummary();
    renderMonthlyHeatmap();

    const trades = (payload.tables.trades || []).slice().reverse();
    document.getElementById('tradeRows').innerHTML = trades.map(t => {{
      const sideCls = String(t.side).toUpperCase() === 'BUY' ? 'up' : 'down';
      const pnlCls = Number(t.realized_pnl) >= 0 ? 'up' : 'down';
      return `<tr>
        <td>${{t.trade_date}}</td>
        <td>${{t.ts_code}}</td>
        <td class="${{sideCls}}">${{t.side}}</td>
        <td>${{fmtNum(t.volume)}}</td>
        <td>${{fmtNum(t.price)}}</td>
        <td>${{fmtNum(t.amount)}}</td>
        <td>${{fmtNum(t.commission)}}</td>
        <td>${{fmtNum(t.stamp_duty)}}</td>
        <td class="${{pnlCls}}">${{fmtNum(t.realized_pnl)}}</td>
      </tr>`;
    }}).join('');
    document.getElementById('footer').textContent = `生成时间: ${{payload.generated_at}}`;
  </script>
</body>
</html>"""
    target.write_text(html, encoding="utf-8")
    return target


def create_demo_payload() -> Dict[str, Any]:
    dates = pd.date_range("2025-01-02", periods=180, freq="B")
    drift = np.linspace(0.0006, 0.0011, len(dates))
    wave = np.sin(np.linspace(0, 12, len(dates))) * 0.006
    shock = np.where((np.arange(len(dates)) % 37) == 0, -0.022, 0)
    daily_returns = pd.Series(drift + wave + shock, index=dates)

    initial_capital = 1_000_000.0
    equity_curve = (1 + daily_returns).cumprod() * initial_capital
    trades = pd.DataFrame(
        {
            "trade_date": dates[::9][:18],
            "ts_code": ["600000.SH", "000001.SZ", "600519.SH"] * 6,
            "side": ["buy", "sell", "buy", "buy", "sell", "sell"] * 3,
            "volume": [1200, 1200, 300, 800, 500, 600] * 3,
            "price": np.linspace(12.4, 48.9, 18),
            "amount": np.linspace(14880, 29340, 18),
            "commission": np.linspace(5.0, 14.2, 18),
            "stamp_duty": np.linspace(0.0, 23.0, 18),
            "realized_pnl": np.linspace(-1800, 4200, 18),
        }
    )

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve / rolling_max) - 1.0
    annual_return = (equity_curve.iloc[-1] / initial_capital) ** (252 / len(dates)) - 1
    sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)

    result = BacktestResult(
        start_date=dates[0].to_pydatetime(),
        end_date=dates[-1].to_pydatetime(),
        initial_capital=initial_capital,
        final_value=float(equity_curve.iloc[-1]),
        total_return=float((equity_curve.iloc[-1] / initial_capital) - 1),
        annual_return=float(annual_return),
        max_drawdown=float(drawdown.min()),
        sharpe_ratio=float(sharpe),
        trade_count=len(trades),
        win_rate=0.56,
        daily_returns=daily_returns,
        equity_curve=equity_curve,
        trades=trades,
    )
    return build_report_payload(
        result=result,
        strategy_name="示例策略组合",
        title="量化回测看板",
        subtitle="可直接接入真实回测结果的本地分析界面",
    )
