import React from "react";
import { valueTone } from "../lib/formatters";

export function TradeTable({ trades }) {
  return (
    <div className="table-wrap"><table><thead><tr><th>日期</th><th>代码/名称</th><th>方向</th><th className="align-right">成交价</th><th className="align-right">数量</th></tr></thead><tbody>
      {trades.map((trade, index) => <tr key={`${trade.trade_date}-${trade.ts_code}-${index}`}><td className="muted">{trade.trade_date}</td><td><strong>{trade.ts_code}</strong><small className="mono block muted">{trade.side}</small></td><td><span className={trade.side === "BUY" ? "trade-buy" : "trade-sell"}>{trade.side === "BUY" ? "买入" : "卖出"}</span></td><td className="align-right mono">¥{Number(trade.price || 0).toFixed(2)}</td><td className="align-right mono">{trade.volume}</td></tr>)}
      {trades.length === 0 && <tr><td colSpan="5"><div className="empty-state">当前报告暂无交易明细。</div></td></tr>}
    </tbody></table></div>
  );
}

export function MetricSummaryTable({ groups, loading }) {
  if (loading) {
    return (
      <section className="panel metric-summary-panel">
        <div className="panel-title"><h3>回测指标总表</h3><span className="muted">正在读取后端报告...</span></div>
        <div className="empty-state">报告数据加载中。</div>
      </section>
    );
  }
  if (!groups.length) return null;
  return (
    <section className="panel no-padding metric-summary-panel">
      <div className="panel-title padded">
        <h3>回测指标总表</h3>
        <span className="muted">来自本地 JSON 报告</span>
      </div>
      <div className="metric-summary-table">
        {groups.map((group) => (
          <div className="metric-summary-group" key={group.group}>
            <div className="metric-group-label">{group.group}</div>
            {group.items.map(([label, value]) => (
              <article className="metric-summary-cell" key={`${group.group}-${label}`}>
                <span>{label}</span>
                <strong className={valueTone(value)}>{value}</strong>
              </article>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
