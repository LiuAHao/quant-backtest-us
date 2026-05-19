import React from "react";
import { formatReportValue, monthHeatStyle } from "../lib/formatters";

export function MonthlyHeatmap({ rows }) {
  const yearMap = rows.reduce((acc, item) => {
    const [year, month] = String(item.month || "").split("-");
    if (!year || !month) return acc;
    if (!acc.has(year)) acc.set(year, new Map());
    acc.get(year).set(Number(month), Number(item.return || 0));
    return acc;
  }, new Map());
  const years = [...yearMap.keys()].sort();
  const months = Array.from({ length: 12 }, (_, index) => index + 1);

  if (rows.length === 0) {
    return <div className="monthly-heatmap-empty"><div className="empty-state">当前报告暂无月度收益数据。</div></div>;
  }

  return (
    <div className="monthly-heatmap-wrap">
      <div className="monthly-heatmap">
        <div className="heatmap-corner" />
        {months.map((month) => <div className="heatmap-month" key={month}>{month}</div>)}
        {years.map((year) => (
          <React.Fragment key={year}>
            <div className="heatmap-year">{year}</div>
            {months.map((month) => {
              const value = yearMap.get(year)?.get(month);
              const hasValue = value !== undefined;
              return (
                <div className={hasValue ? "heatmap-cell" : "heatmap-cell empty"} style={monthHeatStyle(value)} key={`${year}-${month}`}>
                  {hasValue ? formatReportValue(value, "pct") : "-"}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
