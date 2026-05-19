import React from "react";
import { Trash2, XCircle } from "lucide-react";
import { StatusBadge } from "./display";

export function BacktestTable({ rows, onOpen, onCancel, onDelete, compact = false }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>回测 ID</th><th>策略名称</th><th>区间</th><th>状态</th>
            <th className="align-right">总收益</th><th className="align-right">最大回撤</th><th className="align-right">夏普</th>
            {!compact && <th>创建时间</th>}<th className="align-center">操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.id}>
              <td className="mono muted">{item.id}</td>
              <td><strong>{item.strategy}</strong><small className="block muted">{item.source}</small></td>
              <td className="muted">{item.period}</td>
              <td><StatusBadge status={item.status} /></td>
              <td className={`align-right strong ${item.totalReturn !== "-" && item.totalReturn.startsWith("-") ? "text-down" : "text-up"}`}>{item.totalReturn}</td>
              <td className="align-right strong text-down">{item.drawdown}</td>
              <td className="align-right strong">{item.sharpe}</td>
              {!compact && <td className="muted">{item.createdAt}</td>}
              <td className="align-center">
                <div className="row-actions">
                  <button className="link-button" disabled={compact ? item.status !== "success" : ["queued", "running"].includes(item.status)} onClick={() => onOpen(item)}>查看</button>
                  {!compact && ["queued", "running"].includes(item.status) && (
                    <button className="text-action danger-action" title="终止回测" onClick={() => onCancel?.(item)}>
                      <XCircle size={16} />终止
                    </button>
                  )}
                  {!compact && !["queued", "running"].includes(item.status) && (
                    <button className="text-action danger-action" title="删除回测结果" onClick={() => onDelete?.(item)}>
                      <Trash2 size={16} />删除
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={compact ? 8 : 9}><div className="empty-state">后端暂无回测记录。</div></td></tr>}
        </tbody>
      </table>
    </div>
  );
}
