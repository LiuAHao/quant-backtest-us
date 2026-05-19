import React from "react";

export function RuntimeLogPanel({ title, logs, loading, errorMessage, emptyText }) {
  return (
    <section className="panel no-padding">
      <div className="panel-title padded">
        <h3>{title}</h3>
        <span className="muted">{logs.length ? `已记录 ${logs.length} 条` : "按任务时间顺序展示"}</span>
      </div>
      <div className="runtime-log-wrap">
        {errorMessage && <div className="runtime-log-error">{errorMessage}</div>}
        {loading && <div className="empty-state">正在读取日志...</div>}
        {!loading && !logs.length && <div className="empty-state">{emptyText}</div>}
        {!loading && logs.length > 0 && (
          <div className="runtime-log-list">
            {logs.map((item, index) => (
              <div className="runtime-log-item" key={`${item.timestamp}-${item.level}-${index}`}>
                <span className="runtime-log-meta">{item.timestamp} [{item.level}] {item.source}</span>
                <code>{item.message}</code>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
