import React, { useState } from "react";
import { formatReportValue, valueTone } from "../lib/formatters";

export function MiniLineChart({ data, height = 320, tradesByDate = new Map() }) {
  const [hover, setHover] = useState(null);
  if (!data || data.length < 2) {
    return <div className="empty-state">当前报告暂无可绘制的净值曲线。</div>;
  }
  const minVal = Math.min(...data.map((item) => item.portfolio));
  const maxVal = Math.max(...data.map((item) => item.portfolio));
  const padding = (maxVal - minVal) * 0.1;
  const yMin = minVal - padding;
  const yMax = maxVal + padding;
  const range = yMax - yMin || 1;
  const point = (value, index, width) => `${((index / (data.length - 1)) * width).toFixed(2)},${(height - ((value - yMin) / range) * height).toFixed(2)}`;
  const path = (key, width) => `M ${data.map((item, index) => point(item[key], index, width)).join(" L ")}`;
  const area = (key, width) => `M 0,${height} L ${data.map((item, index) => point(item[key], index, width)).join(" L ")} L ${width},${height} Z`;
  const labels = [data[0]?.date, data[Math.floor(data.length / 2)]?.date, data[data.length - 1]?.date];
  const hoverX = hover ? (hover.index / (data.length - 1)) * 100 : 0;
  const hoverTrades = hover ? tradesByDate.get(hover.date) || [] : [];
  const onMove = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.min(Math.max(event.clientX - rect.left - 46, 0), rect.width - 46);
    const index = Math.round((x / Math.max(rect.width - 46, 1)) * (data.length - 1));
    setHover({ ...data[index], index });
  };
  return (
    <div className="chart-box" style={{ height: height + 34 }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <div className="y-axis" style={{ height }}><span>{yMax.toFixed(2)}</span><span>{((yMax + yMin) / 2).toFixed(2)}</span><span>{yMin.toFixed(2)}</span></div>
      <svg viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none" className="chart-svg" style={{ height }}>
        <defs><linearGradient id="portfolioArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2563eb" stopOpacity="0.2" /><stop offset="100%" stopColor="#2563eb" stopOpacity="0" /></linearGradient></defs>
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => <line key={tick} x1="0" x2="1000" y1={height * tick} y2={height * tick} className="grid-line" />)}
        <path d={area("portfolio", 1000)} fill="url(#portfolioArea)" /><path d={path("portfolio", 1000)} fill="none" className="portfolio-line" />
        {hover && <line x1={hover.index / (data.length - 1) * 1000} x2={hover.index / (data.length - 1) * 1000} y1="0" y2={height} className="hover-line" />}
      </svg>
      {hover && (
        <div className="chart-tooltip" style={{ left: `calc(46px + ${hoverX}% )` }}>
          <strong>{hover.date}</strong>
          <span>当日收益：<b className={valueTone(formatReportValue(hover.dailyReturn, "pct"))}>{formatReportValue(hover.dailyReturn, "pct")}</b></span>
          <span>累计收益：<b className={valueTone(formatReportValue(hover.cumulativeReturn, "pct"))}>{formatReportValue(hover.cumulativeReturn, "pct")}</b></span>
          <div className="tooltip-trades">
            {hoverTrades.length > 0 ? hoverTrades.slice(0, 5).map((trade, index) => (
              <em key={`${trade.ts_code}-${trade.side}-${index}`}>{trade.side === "BUY" ? "买入" : "卖出"} {trade.ts_code} {trade.volume}</em>
            )) : <em>当日无交易</em>}
            {hoverTrades.length > 5 && <em>另有 {hoverTrades.length - 5} 笔交易</em>}
          </div>
        </div>
      )}
      <div className="x-axis">{labels.map((label) => <span key={label}>{label}</span>)}</div>
    </div>
  );
}
