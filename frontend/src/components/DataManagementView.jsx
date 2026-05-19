import React, { useState } from "react";
import {
  Activity,
  AlertCircle,
  Calendar,
  CheckCircle2,
  ClipboardCopy,
  Database,
  XCircle,
} from "lucide-react";
import { MetricCard } from "./display";

export function DataManagementView({ notify, runtimeSettings, apiOnline }) {
  const [visibleCmd, setVisibleCmd] = useState(null);
  const data = runtimeSettings?.data || {};
  const latestTradeDate = data.latest_trade_date;
  const earliestTradeDate = data.earliest_trade_date;

  const today = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const cmdValidate = "./.venv/bin/python scripts/data_admin.py validate --days 10 --json";
  const cmdDownload = `./.venv/bin/python scripts/download_by_date.py --start ${today} --end ${today}`;
  const cmdExtra = `./.venv/bin/python scripts/update_extra_data.py --start ${today} --end ${today} --tasks daily_basic stk_limit`;

  const copyCmd = (cmd) => {
    navigator.clipboard.writeText(cmd).then(() => notify("已复制", cmd));
  };

  const CommandReveal = ({ id, cmd }) => (
    visibleCmd === id && (
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, gridColumn: "1 / -1" }}>
        <code style={{ flex: 1, padding: "8px 10px", background: "var(--surface-soft, #f5f5f5)", borderRadius: 6, fontSize: 12, fontFamily: "monospace", border: "1px solid var(--line, #e5e5e5)", wordBreak: "break-all" }}>{cmd}</code>
        <button className="secondary-action" style={{ flexShrink: 0 }} onClick={() => copyCmd(cmd)}><ClipboardCopy size={14} /></button>
      </div>
    )
  );

  return (
    <div className="view-stack page-enter">
      <div className="view-title-row"><div><h2>数据管理</h2><p>查看本地数据状态，获取数据更新和校验命令。</p></div></div>
      <section className="maintenance-grid">
        <MetricCard label="API 状态" value={apiOnline ? "在线" : "离线"} hint={apiOnline ? "后端已连接" : "请启动 uvicorn"} icon={apiOnline ? CheckCircle2 : XCircle} tone={apiOnline ? "good" : "bad"} />
        <MetricCard label="最新交易日" value={latestTradeDate || "-"} hint={earliestTradeDate ? `${earliestTradeDate} 至 ${latestTradeDate}` : "暂无数据"} icon={Calendar} tone={latestTradeDate ? "good" : "neutral"} />
        <MetricCard label="数据校验" value="未运行" hint="需从命令行执行校验" icon={AlertCircle} />
      </section>
      <section className="panel">
        <div className="panel-title"><h3>数据任务</h3><p style={{ color: "var(--muted, #888)", fontSize: 13, marginTop: 4 }}>点击按钮查看对应命令，复制后在终端执行。</p></div>
        <div className="task-cards">
          <button onClick={() => setVisibleCmd(visibleCmd === "validate" ? null : "validate")}><AlertCircle size={18} />校验数据质量<span>scripts/data_admin.py validate</span></button>
          <button onClick={() => setVisibleCmd(visibleCmd === "download" ? null : "download")}><Database size={18} />更新日线行情<span>scripts/download_by_date.py</span></button>
          <button onClick={() => setVisibleCmd(visibleCmd === "extra" ? null : "extra")}><Activity size={18} />更新扩展数据<span>scripts/update_extra_data.py</span></button>
          <CommandReveal id="validate" cmd={cmdValidate} />
          <CommandReveal id="download" cmd={cmdDownload} />
          <CommandReveal id="extra" cmd={cmdExtra} />
        </div>
      </section>
    </div>
  );
}
